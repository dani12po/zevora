"""Static provider example analysis. Source text is parsed, never executed."""
from __future__ import annotations

import ast
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

MAX_SCRIPT_BYTES = 512 * 1024


@dataclass(frozen=True)
class ScriptAnalysis:
    language: str
    protocol: str = "unknown"
    base_url: str = ""
    model: str = ""
    credential_env: str = ""
    stream: bool | None = None
    request_options: dict[str, Any] = field(default_factory=dict)
    extra_body: dict[str, Any] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    sdk_type: str = "unknown"
    request_format: str = "unknown"
    confidence: float = 0.0
    confidence_level: str = "LOW"
    requires_runtime: bool = False
    uncertain_fields: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["uncertain_fields"] = list(self.uncertain_fields)
        data["warnings"] = list(self.warnings)
        return data


class ScriptAnalyzer:
    def analyze(self, source: str, language: str = "auto") -> ScriptAnalysis:
        if len(source.encode("utf-8")) > MAX_SCRIPT_BYTES:
            raise ValueError("provider example exceeds 512 KB")
        selected = self._detect_language(source) if language.lower() == "auto" else language.lower()
        if selected in {"python", "py"}:
            return PythonScriptAnalyzer().analyze(source)
        if selected in {"node", "javascript", "js", "typescript", "ts"}:
            return NodeScriptAnalyzer().analyze(source, selected)
        if selected in {"shell", "bash", "sh", "curl"}:
            return ShellScriptAnalyzer().analyze(source)
        return ScriptAnalysis(
            language=selected or "unknown", requires_runtime=True,
            uncertain_fields=("protocol", "base_url", "model", "credential_env"),
            warnings=("ZEVORA could not safely identify the script language.",),
        )

    @staticmethod
    def _detect_language(source: str) -> str:
        lowered = source.lower()
        if re.search(r"\b(from\s+\w+\s+import|import\s+\w+|requests\.|httpx\.|os\.getenv)", source):
            return "python"
        if re.search(r"\b(const|let|var|require\(|process\.env|fetch\(|axios\.|new\s+openai)", lowered):
            return "node"
        if re.search(r"(^|\s)curl\s+", source, re.MULTILINE):
            return "shell"
        return "unknown"


class PythonScriptAnalyzer:
    def analyze(self, source: str) -> ScriptAnalysis:
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return ScriptAnalysis(
                language="python", requires_runtime=True,
                uncertain_fields=("protocol", "base_url", "model", "credential_env"),
                warnings=("Python syntax could not be parsed safely.",),
            )
        imports = self._imports(tree)
        protocol = "unknown"
        sdk = "python"
        request_format = "custom"
        if "openai" in imports:
            protocol, sdk, request_format = "openai-compatible", "openai-python", "chat-completions"
        elif "anthropic" in imports:
            protocol, sdk, request_format = "anthropic-compatible", "anthropic-python", "messages"
        elif imports & {"requests", "httpx"}:
            protocol, sdk, request_format = "http-rest", sorted(imports & {"requests", "httpx"})[0], "json"
        values: dict[str, Any] = {}
        calls: list[ast.Call] = []
        dynamic_calls = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                calls.append(node)
                name = self._call_name(node.func)
                if name in {"eval", "exec", "compile", "__import__", "custom_auth", "create_signature"}:
                    dynamic_calls = True
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                literal = self._literal(node.value)
                if literal is not None:
                    values[node.targets[0].id] = literal
        base_url = model = credential = ""
        stream: bool | None = None
        options: dict[str, Any] = {}
        extra_body: dict[str, Any] = {}
        headers: dict[str, str] = {}
        direct_hits = 0
        for call in calls:
            kwargs = {item.arg: item.value for item in call.keywords if item.arg}
            if not base_url and "base_url" in kwargs:
                base_url = str(self._resolve(kwargs["base_url"], values) or "")
                direct_hits += bool(base_url)
            if not model and "model" in kwargs:
                model = str(self._resolve(kwargs["model"], values) or "")
                direct_hits += bool(model)
            if "stream" in kwargs:
                resolved = self._resolve(kwargs["stream"], values)
                stream = resolved if isinstance(resolved, bool) else None
            for key in ("temperature", "top_p", "max_tokens", "max_completion_tokens"):
                if key in kwargs:
                    resolved = self._resolve(kwargs[key], values)
                    if isinstance(resolved, (int, float, bool, str)):
                        options[key] = resolved
            if "extra_body" in kwargs:
                resolved = self._resolve(kwargs["extra_body"], values)
                if isinstance(resolved, dict):
                    extra_body = resolved
            if "headers" in kwargs or "default_headers" in kwargs:
                resolved = self._resolve(kwargs.get("headers") or kwargs.get("default_headers"), values)
                if isinstance(resolved, dict):
                    headers = {str(k): self._safe_header(str(v)) for k, v in resolved.items()}
            if not credential:
                for key in ("api_key", "token", "auth_token"):
                    if key in kwargs:
                        credential = self._credential_name(kwargs[key])
                        direct_hits += bool(credential)
        if protocol == "http-rest" and not base_url:
            for call in calls:
                name = self._call_name(call.func)
                if name.endswith((".post", ".get", ".request")) and call.args:
                    resolved = self._resolve(call.args[0], values)
                    if isinstance(resolved, str) and resolved.startswith(("http://", "https://")):
                        base_url = resolved
                        direct_hits += 1
                        break
        if protocol == "unknown" or dynamic_calls:
            requires_runtime = True
            if protocol == "unknown":
                protocol = "custom-runtime"
        else:
            requires_runtime = False
        uncertain = tuple(field for field, value in (
            ("base_url", base_url), ("model", model), ("credential_env", credential)
        ) if not value)
        confidence = min(0.99, 0.45 + direct_hits * 0.15 + (0.15 if protocol != "custom-runtime" else 0))
        return ScriptAnalysis(
            language="python", protocol=protocol, base_url=base_url, model=model,
            credential_env=credential, stream=stream, request_options=options,
            extra_body=extra_body, headers=headers, sdk_type=sdk,
            request_format=request_format, confidence=round(confidence, 2),
            confidence_level=_level(confidence), requires_runtime=requires_runtime,
            uncertain_fields=uncertain,
            warnings=(("Custom authentication or executable logic requires a restricted runtime.",)
                      if requires_runtime else ()),
        )

    @staticmethod
    def _imports(tree: ast.AST) -> set[str]:
        found = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.update(alias.name.split(".")[0].lower() for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                found.add(node.module.split(".")[0].lower())
        return found

    @staticmethod
    def _call_name(node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return f"{PythonScriptAnalyzer._call_name(node.value)}.{node.attr}".strip(".")
        return ""

    @staticmethod
    def _literal(node: ast.AST) -> Any:
        try:
            return ast.literal_eval(node)
        except (ValueError, TypeError):
            return None

    def _resolve(self, node: ast.AST, values: dict[str, Any]) -> Any:
        if isinstance(node, ast.Name):
            return values.get(node.id)
        return self._literal(node)

    def _credential_name(self, node: ast.AST) -> str:
        if isinstance(node, ast.Call):
            name = self._call_name(node.func)
            if name in {"os.getenv", "os.environ.get"} and node.args:
                value = self._literal(node.args[0])
                return value if isinstance(value, str) else ""
        if isinstance(node, ast.Subscript) and self._call_name(node.value) == "os.environ":
            value = self._literal(node.slice)
            return value if isinstance(value, str) else ""
        return ""

    @staticmethod
    def _safe_header(value: str) -> str:
        if re.search(r"(?i)(bearer\s+[A-Za-z0-9._-]{8,}|sk-[A-Za-z0-9_-]{8,})", value):
            return "[REDACTED]"
        return value


class NodeScriptAnalyzer:
    def analyze(self, source: str, language: str = "node") -> ScriptAnalysis:
        lowered = source.lower()
        protocol = "unknown"
        sdk = "node"
        request_format = "custom"
        if re.search(r"(?:from\s+['\"]openai|require\(['\"]openai|new\s+openai)", source, re.I):
            protocol, sdk, request_format = "openai-compatible", "openai-node", "chat-completions"
        elif "anthropic" in lowered:
            protocol, sdk, request_format = "anthropic-compatible", "anthropic-node", "messages"
        elif "fetch(" in lowered or "axios." in lowered:
            protocol, sdk, request_format = "http-rest", "fetch" if "fetch(" in lowered else "axios", "json"
        base_url = _first(source, [
            r"baseURL\s*:\s*['\"]([^'\"]+)", r"base_url\s*:\s*['\"]([^'\"]+)",
            r"(?:fetch|axios\.post)\(\s*['\"](https?://[^'\"]+)",
        ])
        model = _first(source, [r"model\s*:\s*['\"]([^'\"]+)"])
        credential = _first(source, [
            r"process\.env\.([A-Z_][A-Z0-9_]*)", r"process\.env\[['\"]([A-Z_][A-Z0-9_]*)['\"]\]",
        ])
        stream_raw = _first(source, [r"stream\s*:\s*(true|false)"])
        stream = stream_raw.lower() == "true" if stream_raw else None
        options: dict[str, Any] = {}
        for key in ("temperature", "top_p", "max_tokens", "max_completion_tokens"):
            raw = _first(source, [rf"{key}\s*:\s*([-+]?\d+(?:\.\d+)?)"])
            if raw:
                options[key] = float(raw) if "." in raw else int(raw)
        requires_runtime = protocol == "unknown" or bool(re.search(
            r"customAuthentication|createSignature|customSDK|child_process|exec\(", source, re.I
        ))
        if requires_runtime:
            protocol = "custom-runtime"
        hits = sum(bool(item) for item in (base_url, model, credential))
        confidence = min(.96, .4 + hits * .16 + (.12 if protocol != "custom-runtime" else 0))
        uncertain = tuple(field for field, value in (
            ("base_url", base_url), ("model", model), ("credential_env", credential)
        ) if not value)
        return ScriptAnalysis(
            language="typescript" if language in {"typescript", "ts"} else "node",
            protocol=protocol, base_url=base_url, model=model, credential_env=credential,
            stream=stream, request_options=options, sdk_type=sdk,
            request_format=request_format, confidence=round(confidence, 2),
            confidence_level=_level(confidence), requires_runtime=requires_runtime,
            uncertain_fields=uncertain,
            warnings=(("Dynamic JavaScript or custom SDK logic requires a restricted runtime.",)
                      if requires_runtime else ()),
        )


class ShellScriptAnalyzer:
    def analyze(self, source: str) -> ScriptAnalysis:
        if not re.search(r"(^|\s)curl\s+", source, re.MULTILINE):
            return ScriptAnalysis(
                language="shell", protocol="custom-runtime", requires_runtime=True,
                uncertain_fields=("protocol", "base_url", "model", "credential_env"),
                warnings=("Only static curl examples can be converted safely.",),
            )
        url = _first(source, [r"https?://[^\s'\"\\]+"])
        model = _first(source, [r"['\"]model['\"]\s*:\s*['\"]([^'\"]+)"])
        credential = _first(source, [
            r"\$\{([A-Z_][A-Z0-9_]*)\}", r"\$([A-Z_][A-Z0-9_]*)",
        ])
        protocol = "openai-compatible" if "/chat/completions" in url else "http-rest"
        base_url = url.split("/chat/completions", 1)[0] if protocol == "openai-compatible" else url
        stream_raw = _first(source, [r"['\"]stream['\"]\s*:\s*(true|false)"])
        stream = stream_raw.lower() == "true" if stream_raw else None
        hits = sum(bool(item) for item in (base_url, model, credential))
        confidence = min(.95, .45 + hits * .16)
        return ScriptAnalysis(
            language="shell", protocol=protocol, base_url=base_url, model=model,
            credential_env=credential, stream=stream, sdk_type="curl", request_format="json",
            confidence=round(confidence, 2), confidence_level=_level(confidence),
            uncertain_fields=tuple(field for field, value in (
                ("base_url", base_url), ("model", model), ("credential_env", credential)
            ) if not value),
        )


def _first(source: str, patterns: list[str]) -> str:
    for pattern in patterns:
        match = re.search(pattern, source, re.I | re.M)
        if match:
            return match.group(1) if match.lastindex else match.group(0)
    return ""


def _level(confidence: float) -> str:
    if confidence >= .85:
        return "HIGH"
    if confidence >= .65:
        return "MEDIUM"
    return "LOW"
