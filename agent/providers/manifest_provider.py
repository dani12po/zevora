"""Provider-agnostic HTTP and custom-runtime adapters."""
from __future__ import annotations

from time import perf_counter
from typing import Any

import httpx

from agent.config import settings
from .base import AIProvider
from .configuration import ProviderManifest, ProviderStore
from .credentials import CredentialResolver
from .errors import (
    ModelNotFoundError, ProviderAuthenticationError, ProviderError,
    map_http_error, raise_for_response,
)
from .runtime import CustomRuntimeManager


class ManifestProvider(AIProvider):
    def __init__(
        self, manifest: ProviderManifest,
        resolver: CredentialResolver | None = None,
        runtime_manager: CustomRuntimeManager | None = None,
    ):
        self.manifest = manifest
        self.name = manifest.provider_id
        self.default_model = manifest.default_model
        self.resolver = resolver or CredentialResolver()
        self.runtime_manager = runtime_manager or CustomRuntimeManager(ProviderStore(), self.resolver)
        self.store = self.runtime_manager.store
        self.supports_vision = manifest.capabilities.get("vision") is True

    def configured(self) -> bool:
        if self.manifest.protocol == "custom-runtime":
            try:
                exists = self.store.script_path(self.manifest).is_file()
            except ValueError:
                exists = False
            credential = self.resolver.status(self.manifest.credential)
            return exists and (credential["configured"] or not self.manifest.credential.name)
        credential = self.resolver.status(self.manifest.credential)
        return bool(self.manifest.base_url and (credential["configured"] or not self.manifest.credential.name))

    async def health_check(self) -> bool:
        try:
            if self.manifest.protocol == "custom-runtime":
                if not self.manifest.runtime or not self.manifest.runtime.trusted:
                    return False
                await self.runtime_manager.execute(
                    self.manifest, {"type": "health_check", "model": self.default_model}, approved=False
                )
                return True
            if not self.configured():
                return False
            headers = self._headers()
            path = "/models" if self.manifest.protocol in {
                "openai-compatible", "local-openai-compatible"
            } else ""
            async with httpx.AsyncClient(timeout=settings.provider_timeout_seconds) as client:
                response = await client.get(f"{self.manifest.base_url.rstrip('/')}{path}", headers=headers)
                raise_for_response(self.name, response)
            return True
        except Exception:
            return False

    async def test_connection(self, *, approved: bool = False) -> dict[str, Any]:
        started = perf_counter()
        try:
            if self.manifest.protocol == "custom-runtime":
                result = await self.runtime_manager.execute(
                    self.manifest, {"type": "health_check", "model": self.default_model},
                    approved=approved,
                )
                latency = result.duration_ms
            else:
                if not self.configured():
                    raise ProviderAuthenticationError(f"{self.name} credential is not configured")
                await self.list_models()
                latency = int((perf_counter() - started) * 1000)
            return {
                "success": True, "provider": self.name, "model": self.default_model,
                "latency_ms": latency, "authentication": "valid", "state": "HEALTHY",
            }
        except Exception as error:
            mapped = map_http_error(self.name, error)
            return {
                "success": False, "provider": self.name, "model": self.default_model,
                "latency_ms": int((perf_counter() - started) * 1000),
                "error_category": type(mapped).__name__,
                "message": self.resolver.safe_error(mapped), "state": "FAILED",
            }

    async def list_models(self) -> list[dict[str, Any]]:
        if self.manifest.protocol == "custom-runtime":
            return [self._model(self.default_model)] if self.default_model else []
        if not self.configured():
            return []
        if self.manifest.protocol not in {"openai-compatible", "local-openai-compatible"}:
            return [self._model(self.default_model)] if self.default_model else []
        try:
            async with httpx.AsyncClient(timeout=settings.provider_timeout_seconds) as client:
                response = await client.get(
                    f"{self.manifest.base_url.rstrip('/')}/models", headers=self._headers()
                )
                raise_for_response(self.name, response)
                payload = response.json()
            model_ids = [str(item.get("id")) for item in payload.get("data", [])
                         if isinstance(item, dict) and item.get("id")]
            if self.default_model and self.default_model not in model_ids:
                model_ids.insert(0, self.default_model)
            return [self._model(model_id) for model_id in model_ids]
        except Exception as error:
            mapped = map_http_error(self.name, error)
            raise mapped from error

    async def complete(self, prompt: str, system: str = ""):
        return await self.complete_for_model(prompt, system, self.default_model)

    async def complete_for_model(self, prompt: str, system: str = "", model_id: str = ""):
        model = model_id or self.default_model
        if not model:
            raise ModelNotFoundError(f"{self.name} model is not configured")
        if self.manifest.protocol == "custom-runtime":
            result = await self.runtime_manager.execute(self.manifest, {
                "type": "chat", "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "request_options": self.manifest.request_options,
                "extra_body": self.manifest.extra_body,
            }, approved=False)
            return result.text, result.usage
        if not self.configured():
            raise ProviderAuthenticationError(f"{self.name} credential is not configured")
        payload = self._payload(model, prompt, system)
        return await self._post(payload)

    async def complete_multimodal(self, prompt, images, system="", model_id=""):
        if self.manifest.capabilities.get("vision") is not True:
            raise ProviderError(f"{self.name} does not declare image support")
        model = model_id or self.default_model
        content = [{"type": "text", "text": prompt}]
        content.extend({
            "type": "image_url",
            "image_url": {"url": f"data:{image['media_type']};base64,{image['data_base64']}"},
        } for image in images)
        payload = self._payload(model, content, system)
        return await self._post(payload)

    def _payload(self, model: str, prompt: Any, system: str) -> dict[str, Any]:
        options = dict(self.manifest.request_options)
        options.pop("model", None)
        options.pop("messages", None)
        if self.manifest.protocol == "anthropic-compatible":
            payload = {
                "model": model,
                "system": system,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": options.pop("max_tokens", 1024),
                **options,
            }
        else:
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                **options,
            }
        payload.update(self.manifest.extra_body)
        return payload

    async def _post(self, payload: dict[str, Any]):
        path = {
            "openai-compatible": "/chat/completions",
            "local-openai-compatible": "/chat/completions",
            "anthropic-compatible": "/messages",
            "http-rest": "",
        }.get(self.manifest.protocol, "")
        try:
            async with httpx.AsyncClient(timeout=settings.provider_timeout_seconds) as client:
                response = await client.post(
                    f"{self.manifest.base_url.rstrip('/')}{path}",
                    headers=self._headers(), json=payload,
                )
                raise_for_response(self.name, response)
                data = response.json()
            if self.manifest.protocol == "anthropic-compatible":
                text = "".join(str(item.get("text", "")) for item in data.get("content", [])
                               if isinstance(item, dict) and item.get("type") == "text")
                usage = data.get("usage", {})
            elif self.manifest.protocol == "http-rest":
                text = data.get("response") or data.get("content") or data.get("text")
                usage = data.get("usage", {})
            else:
                message = data["choices"][0]["message"]
                text = message.get("content") or ""
                reasoning = message.get("reasoning_content")
                usage = data.get("usage", {})
                if reasoning:
                    usage = {**usage, "reasoning_content_available": True}
            if not isinstance(text, str):
                raise ValueError("provider response contains no text")
            return text, usage
        except Exception as error:
            mapped = map_http_error(self.name, error)
            raise mapped from error

    def _headers(self) -> dict[str, str]:
        credential = self.resolver.resolve(
            self.manifest.credential, required=bool(self.manifest.credential.name)
        )
        headers = {"Content-Type": "application/json"}
        if self.manifest.protocol == "anthropic-compatible":
            if credential:
                headers["x-api-key"] = credential.value
            headers["anthropic-version"] = "2023-06-01"
        elif credential:
            headers["Authorization"] = f"Bearer {credential.value}"
        headers.update(self.resolver.substitute_headers(self.manifest.headers, credential))
        return headers

    def _model(self, model_id: str) -> dict[str, Any]:
        capabilities = [key for key, value in self.manifest.capabilities.items() if value is True]
        return {
            "model_id": model_id,
            "display_name": model_id,
            "capabilities": capabilities,
            "context_window": self.manifest.context_length,
            "supports_streaming": self.manifest.capabilities.get("streaming"),
            "supports_tools": self.manifest.capabilities.get("tool_calling"),
            "supports_vision": self.manifest.capabilities.get("vision"),
            "supports_reasoning": self.manifest.capabilities.get("reasoning"),
            "supports_code": self.manifest.capabilities.get("code"),
            "supports_json": self.manifest.capabilities.get("json_mode"),
            "input_price": self.manifest.input_price,
            "output_price": self.manifest.output_price,
            "availability": "verified" if self.manifest.state in {"HEALTHY", "TRUSTED_RUNTIME"} else "unknown",
        }
