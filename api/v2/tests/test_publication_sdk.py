"""Exercise the real installed OpenAI SDK using only an in-process transport."""
import asyncio
import json
import importlib
import httpx2
from openai import OpenAI
from test_publication_sync import event, sync_module


def test_real_sdk_production_adapter_offline_transport(monkeypatch):
    controller = importlib.import_module('app.controllers.post_controller')
    from app.publication_generation import generate
    calls = []
    outputs = [json.dumps(['PT ponto'] * 3), json.dumps(['EN point'] * 3), 'English title']

    def handler(request):
        assert request.method == 'POST'
        assert request.url.path == '/v1/chat/completions'
        calls.append(json.loads(request.content))
        return httpx2.Response(200, json=dict(id='offline', object='chat.completion', created=1,
            model='gpt-5-nano', choices=[dict(index=0, finish_reason='stop',
                message=dict(role='assistant', content=outputs[len(calls) - 1]))]))

    with httpx2.Client(transport=httpx2.MockTransport(handler), trust_env=False) as transport:
        with OpenAI(api_key='synthetic-offline-not-a-credential', http_client=transport,
                    max_retries=0, timeout=30.0) as client:
            monkeypatch.setattr(controller, 'openai_client', client)
            result = asyncio.run(generate(sync_module().normalize(event())))
    assert result == dict(summary=['PT ponto'] * 3, summary_en=['EN point'] * 3, title_en='English title')
    assert len(calls) == 3
    assert all(c['model'] == controller.openai_model for c in calls)
    assert 'Texto sintético' in calls[0]['messages'][0]['content']
    assert 'PT ponto' in calls[1]['messages'][0]['content']
    assert 'Título' in calls[2]['messages'][0]['content']
