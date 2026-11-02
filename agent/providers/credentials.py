"""Late-binding provider credentials with secret-free status and substitution."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from agent.config import ROOT
from agent.security.redaction import redact
from .configuration import CredentialReference

_PLACEHOLDER = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")


@dataclass(frozen=True)
class ResolvedCredential:
    name: str
    value: str
    source: str

    @property
    def masked(self) -> str:
        return "********" + self.value[-4:] if len(self.value) >= 4 else "********"


class CredentialResolver:
    """Resolve one declared credential only when a provider request executes."""

    def __init__(self, env_file: Path | None = None, runtime_values: Mapping[str, str] | None = None):
        self.env_file = env_file or ROOT / ".env"
        self.runtime_values = dict(runtime_values or {})

    def resolve(self, reference: CredentialReference, *, required: bool = True) -> ResolvedCredential | None:
        reference.validate()
        if not reference.name:
            if required:
                raise ValueError("provider credential name is not configured")
            return None
        value = ""
        if reference.source == "runtime":
            value = self.runtime_values.get(reference.name, "")
        elif reference.source == "environment":
            value = os.environ.get(reference.name, "") or self._file_environment().get(reference.name, "")
        elif reference.source == "secure-local":
            value = self._secure_local_value(reference.name)
        elif reference.source == "external":
            raise ValueError("external credential provider is not configured")
        if not value and required:
            raise ValueError(f"credential {reference.name} is not configured")
        return ResolvedCredential(reference.name, value, reference.source) if value else None

    def status(self, reference: CredentialReference) -> dict:
        try:
            resolved = self.resolve(reference, required=False)
        except ValueError:
            resolved = None
        return {
            "source": reference.source,
            "name": reference.name,
            "configured": bool(resolved),
            "masked": resolved.masked if resolved else "",
        }

    def substitute_headers(self, headers: Mapping[str, str], credential: ResolvedCredential | None) -> dict[str, str]:
        allowed = {credential.name: credential.value} if credential else {}

        def replace(match: re.Match[str]) -> str:
            name = match.group(1)
            if name not in allowed:
                raise ValueError(f"header references undeclared credential {name}")
            return allowed[name]

        return {str(key): _PLACEHOLDER.sub(replace, str(value)) for key, value in headers.items()}

    def safe_error(self, error: Exception, credential: ResolvedCredential | None = None) -> str:
        message = str(error)
        if credential and credential.value:
            message = message.replace(credential.value, "[REDACTED]")
        return redact(message)

    def _file_environment(self) -> dict[str, str]:
        values: dict[str, str] = {}
        try:
            lines = self.env_file.read_text(encoding="utf-8").splitlines()
        except OSError:
            return values
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                key, _, value = stripped.partition("=")
                values[key.strip().upper()] = value.strip()
        return values

    def _secure_local_value(self, name: str) -> str:
        """Reserved local-store hook; no plaintext fallback is silently used."""
        return self.runtime_values.get(name, "")
