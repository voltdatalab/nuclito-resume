# from app.controllers.post_controller import is_valid_json_array
import re


def is_valid_json_array(arraystr: str) -> bool:
    return (
        re.match(r"""^\[[\n ]?(\t?"[^\"]*",[\n ]?){2}\t?"[^\"]*"[\n ]?\]$""", arraystr)
        is not None
    )


valid_arrays = [
    '["Hello", "World", "!"]',
    '["Sílvio", "Santos", "vem aí"]',
    """[
	"Teste",
	"Com",
	"Barra-ns"
]""",
    '["Teste","Sem","Espaços"]',
    '["Teste",	"Com",	"Tabs"]',
    '["12345",\n"í[]~çäê",\t"😰" ]',
]

invalid_arrays = [
    """[
        {"topico": "assunto"},
        {"topico": "assunto"},
        {"topico": "assunto"}
    ]""",
    "Texto comum",
    "",
    None,
    7,
    '["Ponto", "Fora do", "Lugar".]',
    '["Vírgula", "Sobrando", "no Fim",]',
    '["Dois", "itens"]',
    '["Quatro", "itens", "no", "total"]',
]

for array in valid_arrays:
    if not is_valid_json_array(array):
        print("Erro no array válido:", array)

for array in invalid_arrays:
    try:
        if is_valid_json_array(array):
            print("Erro no array inválido:", array)
    except Exception:
        pass
