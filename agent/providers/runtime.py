"""Restricted custom provider runtimes using structured JSON-lines IPC."""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any
from urllib.parse import urlparse

from agent.config import ROOT, settings
from agent.security.redaction import redact
from .configuration import ProviderManifest, ProviderStore
from .credentials import CredentialResolver, ResolvedCredential
from .errors import ProviderError, ProviderTimeoutError, ProviderUnavailableError

_FORBIDDEN_SOURCE = [
    re.compile(pattern, re.I) for pattern in (
        r"\.ssh", r"id_rsa", r"id_ed25519", r"data[/\\]database",
        r"credential(?:s|_store)?[/\\]", r"\.env(?:\W|$)",
        r"subprocess", r"child_process", r"os\.system", r"popen\(",
        r"fork\(", r"spawn\(", r"powershell", r"cmd\.exe",
        r"/etc/(?:passwd|shadow)", r"windows[/\\]system32",
    )
]
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}
_EVENT_TYPES = {
    "text_delta", "reasoning_delta", "tool_call", "status", "error", "usage", "done", "result",
}


@dataclass(frozen=True)
class RuntimeResult:
    text: str
    usage: dict[str, Any]
    events: tuple[dict[str, Any], ...]
    duration_ms: int
    safe_log: str


class CustomRuntimeManager:
    """Execute one reviewed provider script outside the gateway process."""

    def __init__(self, store: ProviderStore | None = None, resolver: CredentialResolver | None = None):
        self.store = store or ProviderStore()
        self.resolver = resolver or CredentialResolver()
        self._semaphore = asyncio.Semaphore(max(1, settings.custom_runtime_max_concurrency))

    def availability(self) -> dict[str, Any]:
        return {
            "python": bool(sys.executable),
            "node": bool(shutil.which("node")),
            "shell": bool(shutil.which("bash") or shutil.which("sh") or (os.name == "nt" and shutil.which("powershell"))),
            "sandbox": "process-isolated",
            "workspace_mounted": False,
            "structured_ipc": "json-lines",
        }

    async def execute(self, manifest: ProviderManifest, request: dict[str, Any], *, approved: bool = False) -> RuntimeResult:
        if manifest.protocol != "custom-runtime" or manifest.runtime is None:
            raise ProviderError("provider is not a custom runtime")
        if not approved and not manifest.runtime.trusted:
            raise PermissionError("explicit provider runtime approval is required")
        source_path = self.store.script_path(manifest)
        try:
            source = source_path.read_text(encoding="utf-8")
        except OSError as error:
            raise ProviderUnavailableError("provider runtime entrypoint is unavailable") from error
        self._preflight(manifest, source)
        credential = self.resolver.resolve(manifest.credential, required=bool(manifest.credential.name))
        async with self._semaphore:
            return await self._run(manifest, source_path, request, credential)

    def _preflight(self, manifest: ProviderManifest, source: str) -> None:
        if len(source.encode("utf-8")) > 512 * 1024:
            raise ProviderError("provider runtime source exceeds 512 KB")
        for pattern in _FORBIDDEN_SOURCE:
            if pattern.search(source):
                raise PermissionError("provider runtime requests a denied system capability")
        permissions = manifest.runtime.permissions
        allowed_hosts = set(permissions.allowed_hosts)
        if manifest.base_url:
            host = (urlparse(manifest.base_url).hostname or "").lower()
            if host:
                allowed_hosts.add(host)
        if not permissions.network and re.search(r"https?://|socket|requests\.|httpx\.|fetch\(|axios", source, re.I):
            raise PermissionError("provider runtime network permission is disabled")
        if not any(host in _LOCAL_HOSTS for host in allowed_hosts):
            if re.search(r"(?:localhost|127\.0\.0\.1|0\.0\.0\.0|\[?::1\]?)", source, re.I):
                raise PermissionError("provider runtime cannot access undeclared local services")
        if permissions.workspace:
            raise PermissionError("provider runtime workspace access is denied")

    async def _run(
        self, manifest: ProviderManifest, source_path: Path, request: dict[str, Any],
        credential: ResolvedCredential | None,
    ) -> RuntimeResult:
        runtime = manifest.runtime
        assert runtime is not None
        with tempfile.TemporaryDirectory(prefix=f"zevora-provider-{manifest.provider_id}-") as temporary:
            workdir = Path(temporary)
            entrypoint = workdir / runtime.entrypoint
            shutil.copy2(source_path, entrypoint)
            command = self._command(runtime.runtime, entrypoint)
            environment = self._environment(manifest, credential, workdir)
            flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
            started = perf_counter()
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=workdir,
                env=environment,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                creationflags=flags,
            )
            payload = json.dumps(self._safe_request(request), ensure_ascii=True).encode("utf-8") + b"\n"
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(payload), timeout=runtime.timeout_seconds
                )
            except asyncio.TimeoutError as error:
                await self._terminate_tree(process)
                raise ProviderTimeoutError("custom provider timed out") from error
            duration = int((perf_counter() - started) * 1000)
            if len(stdout) + len(stderr) > runtime.max_output_bytes:
                raise ProviderUnavailableError("custom provider exceeded its output limit")
            if self._directory_size(workdir) > runtime.max_temp_bytes:
                raise ProviderUnavailableError("custom provider exceeded its temporary disk limit")
            safe_log = self._sanitize(stderr.decode("utf-8", errors="replace"), credential)[:32_000]
            if process.returncode != 0:
                raise ProviderUnavailableError(
                    f"custom provider runtime exited with code {process.returncode}"
                )
            events = self._parse_events(stdout, credential)
            text = "".join(
                str(event.get("content", "")) for event in events
                if event["type"] in {"text_delta", "result"}
            )
            usage = next((dict(event.get("usage") or {}) for event in events if event["type"] == "usage"), {})
            errors = [event for event in events if event["type"] == "error"]
            if errors:
                raise ProviderUnavailableError(str(errors[-1].get("message") or "custom provider failed"))
            if not text and request.get("type") != "health_check":
                raise ProviderUnavailableError("custom provider returned no response text")
            return RuntimeResult(text, usage, tuple(events), duration, safe_log)

    @staticmethod
    def _command(runtime: str, entrypoint: Path) -> list[str]:
        if runtime == "python":
            return [sys.executable, "-I", "-u", str(entrypoint)]
        if runtime in {"node", "typescript"}:
            executable = shutil.which("node")
            if not executable:
                raise ProviderUnavailableError("Node.js runtime is not installed")
            if runtime == "typescript" and entrypoint.suffix.lower() not in {".js", ".mjs", ".cjs"}:
                raise ProviderUnavailableError("TypeScript runtime requires precompiled JavaScript")
            return [executable, str(entrypoint)]
        executable = shutil.which("bash") or shutil.which("sh")
        if executable:
            return [executable, str(entrypoint)]
        if os.name == "nt" and shutil.which("powershell"):
            return [shutil.which("powershell") or "powershell", "-NoProfile", "-File", str(entrypoint)]
        raise ProviderUnavailableError("shell runtime is not installed")

    @staticmethod
    def _environment(manifest: ProviderManifest, credential: ResolvedCredential | None, workdir: Path) -> dict[str, str]:
        runtime = manifest.runtime
        assert runtime is not None
        allowed_path = os.pathsep.join(filter(None, {
            str(Path(sys.executable).parent),
            str(Path(shutil.which("node") or "").parent) if shutil.which("node") else "",
            str(Path(shutil.which("bash") or shutil.which("sh") or "").parent) if (shutil.which("bash") or shutil.which("sh")) else "",
        }))
        env = {
            "PATH": allowed_path,
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUNBUFFERED": "1",
            "HOME": str(workdir),
            "USERPROFILE": str(workdir),
            "TMP": str(workdir),
            "TEMP": str(workdir),
            "ZEVORA_PROVIDER_ID": manifest.provider_id,
            "ZEVORA_PROVIDER_PROTOCOL": manifest.protocol,
        }
        for key, value in runtime.environment.items():
            env[key] = value
        if credential:
            env[credential.name] = credential.value
        return env

    @staticmethod
    def _safe_request(request: dict[str, Any]) -> dict[str, Any]:
        allowed = {"type", "model", "messages", "prompt", "system", "request_options", "extra_body"}
        return {key: value for key, value in request.items() if key in allowed}

    def _parse_events(self, stdout: bytes, credential: ResolvedCredential | None) -> list[dict[str, Any]]:
        events = []
        for raw_line in stdout.decode("utf-8", errors="replace").splitlines():
            if not raw_line.strip():
                continue
            if len(raw_line.encode("utf-8")) > 1024 * 1024:
                raise ProviderUnavailableError("custom provider emitted an oversized event")
            try:
                event = json.loads(raw_line)
            except json.JSONDecodeError as error:
                raise ProviderUnavailableError("custom provider emitted malformed JSON-lines output") from error
            if not isinstance(event, dict) or event.get("type") not in _EVENT_TYPES:
                raise ProviderUnavailableError("custom provider emitted an unsupported event")
            sanitized = json.loads(self._sanitize(json.dumps(event), credential))
            events.append(sanitized)
        if not events or events[-1].get("type") not in {"done", "result", "error"}:
            raise ProviderUnavailableError("custom provider did not complete its event stream")
        return events

    @staticmethod
    async def _terminate_tree(process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True, check=False,
            )
        else:
            process.kill()
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except asyncio.TimeoutError:
            process.kill()

    @staticmethod
    def _directory_size(path: Path) -> int:
        total = 0
        for item in path.rglob("*"):
            try:
                if item.is_file():
                    total += item.stat().st_size
            except OSError:
                continue
        return total

    @staticmethod
    def _sanitize(value: str, credential: ResolvedCredential | None) -> str:
        if credential and credential.value:
            value = value.replace(credential.value, "[REDACTED]")
        return redact(value)
