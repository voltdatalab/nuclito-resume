"""Production adapter; worker tests inject generation instead of calling a model."""
import importlib
import json


async def generate(item):
    controller = importlib.import_module('app.controllers.post_controller')
    summary = await controller.query_gpt_json(
        'Faça um resumo deste texto em 3 tópicos, usando no máximo 30 palavras para cada tópico. '
        'Retorne apenas um array JSON de 3 strings: ' + item['plaintext'], max_tries=1)
    summary_en = await controller.query_gpt_json(
        'Traduza o array JSON a seguir de português para inglês. Retorne apenas o array JSON: '
        + summary, max_tries=1)
    title_en = await controller.query_gpt_str(
        'Traduza o título a seguir de português para inglês. Retorne apenas o texto do título: '
        + item['title'])
    return dict(summary=json.loads(summary), summary_en=json.loads(summary_en), title_en=title_en)
