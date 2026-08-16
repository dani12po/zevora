import asyncio

import httpx

from agent.models.metadata import ModelMetadata
from agent.models.registry import ModelRegistry
from agent.providers.openai_compatible import OpenAICompatibleProvider
from agent.routing.task_classifier import TaskClassifier
from agent.routing.model_selector import ModelSelector

def test_registry_persists_only_metadata(tmp_path):
    registry=ModelRegistry(tmp_path/'models.db'); registry.upsert(ModelMetadata(provider='mock',model_id='coding-1',capabilities=['coding','reasoning'],availability='verified',health_status='healthy'))
    assert registry.list()[0]['model_id']=='coding-1'

def test_classifier_and_capability_selection():
    task=TaskClassifier().classify('Fix this TypeScript bug')
    models=[{'provider':'mock','model_id':'code','capabilities':['coding','reasoning'],'availability':'verified','health_status':'healthy'}]
    choice=ModelSelector().select(models,task.required_capabilities)
    assert 'coding' in task.required_capabilities and choice.model_id=='code'
def test_unconfigured_provider_has_no_models():
    assert OpenAICompatibleProvider('mock','','https://example.invalid').configured() is False


def test_mixed_catalog_rejects_obvious_non_chat_models():
    supports_chat = OpenAICompatibleProvider._supports_chat
    assert supports_chat('meta/llama-3.1-8b-instruct')
    assert not supports_chat('nvidia/nv-embedqa-e5-v5')
    assert not supports_chat('nvidia/llama-3.1-nemoguard-8b-content-safety')
    assert not supports_chat('nvidia/nv-rerankqa-mistral-4b-v3')


def test_selector_rejects_capability_mismatch():
    choice=ModelSelector().select([{'provider':'mock','model_id':'text','capabilities':['general'],'availability':'verified','health_status':'healthy'}],['vision'])
    assert choice is None


def test_openai_compatible_vision_capability_is_explicit(monkeypatch):
    class Response:
        status_code = 200
        is_success = True
        def raise_for_status(self):
            return None
        def json(self):
            return {'data': [{'id': 'chat-model'}]}

    class Client:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_args):
            return None
        async def get(self, *_args, **_kwargs):
            return Response()

    monkeypatch.setattr(httpx, 'AsyncClient', lambda **_kwargs: Client())
    text_models = asyncio.run(OpenAICompatibleProvider(
        'mock', 'key', 'https://example.invalid', 'chat-model'
    ).list_models())
    vision_models = asyncio.run(OpenAICompatibleProvider(
        'mock', 'key', 'https://example.invalid', 'chat-model', supports_vision=True
    ).list_models())

    assert text_models[0]['supports_vision'] is False
    assert 'vision' not in text_models[0]['capabilities']
    assert vision_models[0]['supports_vision'] is True
    assert 'vision' in vision_models[0]['capabilities']
