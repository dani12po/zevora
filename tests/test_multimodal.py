import asyncio
import base64
import io

import pytest
from pypdf import PdfWriter

from agent.core.attachments import attachment_context, process_attachment
from agent.memory.store import Store
from agent.providers.openai_compatible import OpenAICompatibleProvider
from agent.routing.hybrid_router import AdaptiveHybridRouter, Route


@pytest.fixture(autouse=True)
def enabled_synthetic_provider_policy(monkeypatch):
    """Keep synthetic multimodal models independent from live provider settings."""
    monkeypatch.setattr(
        'agent.routing.hybrid_router.provider_policy',
        lambda _name: {'enabled': True, 'routing_priority': 50, 'default_model': ''},
    )


def encoded(data: bytes) -> str:
    return base64.b64encode(data).decode('ascii')


def test_text_and_json_attachments_are_locally_extracted():
    text = process_attachment('debug.log', 'text/plain', encoded(b'failure on line 12'))
    payload = process_attachment('data.json', 'application/json', encoded(b'{"ok": true}'))

    assert text.kind == 'text'
    assert text.extracted_text == 'failure on line 12'
    assert payload.extracted_text == '{"ok": true}'
    assert 'debug.log' in attachment_context([text])
    assert 'data_base64' not in text.metadata()


def test_invalid_json_and_spoofed_image_are_rejected():
    with pytest.raises(ValueError, match='JSON attachment is invalid'):
        process_attachment('data.json', 'application/json', encoded(b'{bad'))
    with pytest.raises(ValueError, match='does not match image/png'):
        process_attachment('fake.png', 'image/png', encoded(b'not a png'))


def test_image_is_validated_and_retained_only_for_provider_request():
    data = b'\x89PNG\r\n\x1a\n' + b'payload'
    image = process_attachment('screen.png', 'image/png', encoded(data))

    assert image.kind == 'image'
    assert image.image_base64 == encoded(data)
    assert image.extracted_text == ''
    assert image.metadata()['content_hash']
    assert 'image_base64' not in image.metadata()


def test_pdf_is_parsed_without_writing_to_disk():
    buffer = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.write(buffer)

    pdf = process_attachment('report.pdf', 'application/pdf', encoded(buffer.getvalue()))

    assert pdf.kind == 'pdf'
    assert pdf.size_bytes == len(buffer.getvalue())
    assert pdf.image_base64 == ''


def test_attachment_hash_changes_cache_identity(tmp_path):
    store = Store(tmp_path / 'agent.db')
    first = process_attachment('a.txt', 'text/plain', encoded(b'one'))
    second = process_attachment('a.txt', 'text/plain', encoded(b'two'))
    first_context = Store.key('', first.content_hash)
    second_context = Store.key('', second.content_hash)
    store.put_cache('explain', 'first', 'test', 'model', 'general', context_hash=first_context)

    assert store.get_cache('explain', first_context)['response'] == 'first'
    assert store.get_cache('explain', second_context) is None


def test_vision_routing_rejects_text_only_models():
    models = [
        {'provider': 'openai', 'model_id': 'text',
         'capabilities': ['general', 'coding', 'reasoning'],
         'availability': 'verified', 'health_status': 'healthy'},
        {'provider': 'gemini', 'model_id': 'vision',
         'capabilities': ['general', 'coding', 'reasoning', 'vision'],
         'availability': 'verified', 'health_status': 'healthy'},
    ]

    decision = AdaptiveHybridRouter().decide('inspect this [image attachment]', models)

    assert decision.route is Route.CLOUD
    assert decision.provider == 'gemini'
    assert decision.model_id == 'vision'


def test_openai_multimodal_payload_uses_data_url(monkeypatch):
    provider = OpenAICompatibleProvider(
        'custom', 'key', 'https://example.test/v1', 'vision',
        supports_vision=True,
    )
    captured = {}

    async def fake_post(payload):
        captured.update(payload)
        return 'ok', {}

    monkeypatch.setattr(provider, '_post_completion', fake_post)
    response, _ = asyncio.run(provider.complete_multimodal(
        'describe', [{'media_type': 'image/png', 'data_base64': encoded(b'image')}],
        'system', 'vision',
    ))

    content = captured['messages'][1]['content']
    assert response == 'ok'
    assert content[0] == {'type': 'text', 'text': 'describe'}
    assert content[1]['image_url']['url'].startswith('data:image/png;base64,')
