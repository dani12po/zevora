import httpx
from .base import AIProvider
from ..config import settings

class OpenAICompatibleProvider(AIProvider):
    name = 'openai'
    async def complete(self, prompt, system=''):
        if not settings.openai_api_key: raise RuntimeError('OPENAI_API_KEY is not configured')
        headers = {'Authorization': f'Bearer {settings.openai_api_key}'}
        payload = {'model': settings.openai_model, 'messages': [{'role':'system','content':system}, {'role':'user','content':prompt}]}
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(f'{settings.openai_base_url.rstrip("/")}/chat/completions', headers=headers, json=payload)
            response.raise_for_status(); data = response.json()
        return data['choices'][0]['message']['content'], data.get('usage', {})
