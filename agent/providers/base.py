from abc import ABC, abstractmethod

class AIProvider(ABC):
    name: str
    @abstractmethod
    async def complete(self, prompt: str, system: str = '') -> tuple[str, dict]: ...
    async def complete_multimodal(self, prompt: str, images: list[dict], system: str = '',
                                  model_id: str = '') -> tuple[str, dict]:
        raise RuntimeError(f'{self.name} does not support image input')
    async def chat(self, prompt: str, system: str = ''): return await self.complete(prompt, system)
    async def stream(self, prompt: str, system: str = ''):
        """Compatibility stream over the provider's real cloud completion path."""
        response, _usage = await self.complete(prompt, system)
        yield response
    async def health_check(self) -> bool: return False
    async def list_models(self) -> list[dict]: return []
    async def get_model_info(self, model_id: str) -> dict | None:
        return next((model for model in await self.list_models() if model.get('model_id')==model_id),None)
    async def count_tokens(self, text: str) -> int | None: return None
