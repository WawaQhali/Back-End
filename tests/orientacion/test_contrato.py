"""Contrato de Orientacion con preguntas.json v1 (seccion 11, QA-07)."""

import uuid

import httpx
import pytest

from app.modules.orientacion.servicio import CUESTIONARIO
from tests.ayudas import RESPUESTAS_V1, cabeceras_app

pytestmark = pytest.mark.bd


def _consulta(**cambios) -> dict:  # noqa: ANN003
    base = {
        "severidad": "leve",
        "clase": "compatible",
        "confianza": 0.91,
        "version_cuestionario": "v1",
        "respuestas": dict(RESPUESTAS_V1),
    }
    return {**base, **cambios}


async def _post(cliente: httpx.AsyncClient, cuerpo: dict) -> httpx.Response:
    return await cliente.post("/v1/orientacion", json=cuerpo, headers=cabeceras_app(uuid.uuid4()))


def test_cuestionario_v1_se_carga_con_8_de_riesgo_y_6_normales() -> None:
    assert CUESTIONARIO.version == "v1"
    tipos = [p.tipo for p in CUESTIONARIO.preguntas]
    assert tipos.count("riesgo") == 8
    assert tipos.count("normal") == 6
    assert CUESTIONARIO.preguntas[0].id == "dificultad_respirar"
    assert "106" in CUESTIONARIO.mensaje_emergencia


async def test_version_distinta_responde_422(cliente_bd: httpx.AsyncClient) -> None:
    r = await _post(cliente_bd, _consulta(version_cuestionario="v0"))
    assert r.status_code == 422
    assert r.json()["error"]["codigo"] == "version_cuestionario"


async def test_id_desconocido_responde_422(cliente_bd: httpx.AsyncClient) -> None:
    r = await _post(cliente_bd, _consulta(respuestas={**RESPUESTAS_V1, "fiebre": True}))
    assert r.status_code == 422
    assert r.json()["error"]["codigo"] == "pregunta_desconocida"


async def test_opcion_inexistente_responde_422(cliente_bd: httpx.AsyncClient) -> None:
    r = await _post(cliente_bd, _consulta(respuestas={**RESPUESTAS_V1, "extension": "todo"}))
    assert r.status_code == 422
    assert r.json()["error"]["codigo"] == "respuesta_invalida"


async def test_opcion_de_v0_que_ya_no_existe_responde_422(cliente_bd: httpx.AsyncClient) -> None:
    r = await _post(cliente_bd, _consulta(respuestas={**RESPUESTAS_V1, "desencadenante": "otro"}))
    assert r.status_code == 422


@pytest.mark.parametrize("valor", ["si", "true", 1])
async def test_si_no_solo_acepta_booleanos(cliente_bd: httpx.AsyncClient, valor: object) -> None:
    r = await _post(cliente_bd, _consulta(respuestas={**RESPUESTAS_V1, "picazon": valor}))
    assert r.status_code == 422


async def test_opcion_no_acepta_booleano(cliente_bd: httpx.AsyncClient) -> None:
    r = await _post(cliente_bd, _consulta(respuestas={**RESPUESTAS_V1, "extension": True}))
    assert r.status_code == 422


@pytest.mark.parametrize("severidad", ["leve", "moderada"])
async def test_riesgo_en_true_sin_severidad_alta_responde_422(
    cliente_bd: httpx.AsyncClient, severidad: str
) -> None:
    respuestas = {**RESPUESTAS_V1, "labios_morados": True}
    r = await _post(cliente_bd, _consulta(severidad=severidad, respuestas=respuestas))
    assert r.status_code == 422
    assert r.json()["error"]["codigo"] == "severidad_incoherente"


async def test_riesgo_en_true_con_severidad_alta_pasa_la_validacion(
    cliente_bd: httpx.AsyncClient,
) -> None:
    # Con "si" el cuestionario se detiene: solo llegan las de riesgo hasta ese punto.
    respuestas = {"dificultad_respirar": False, "labios_morados": True}
    r = await _post(cliente_bd, _consulta(severidad="alta", respuestas=respuestas))
    assert r.status_code != 422  # sin guias cargadas termina en 503, no en 422


async def test_texto_libre_de_mas_de_200_caracteres_responde_422(
    cliente_bd: httpx.AsyncClient,
) -> None:
    r = await _post(cliente_bd, _consulta(texto_libre="x" * 201))
    assert r.status_code == 422


@pytest.mark.parametrize("edad", [0, 5, -1, "2", True])
async def test_edad_fuera_de_1_a_4_anios_responde_422(
    cliente_bd: httpx.AsyncClient, edad: int
) -> None:
    r = await _post(cliente_bd, _consulta(edad_anios=edad, sexo="femenino"))
    assert r.status_code == 422


async def test_sexo_invalido_responde_422(cliente_bd: httpx.AsyncClient) -> None:
    r = await _post(cliente_bd, _consulta(edad_anios=2, sexo="otro"))
    assert r.status_code == 422


@pytest.mark.parametrize("edad", [1, 2, 3, 4])
async def test_edad_de_1_a_4_y_sexo_pasan_la_validacion(
    cliente_bd: httpx.AsyncClient, edad: int
) -> None:
    r = await _post(cliente_bd, _consulta(edad_anios=edad, sexo="masculino"))
    assert r.status_code != 422  # sin guias cargadas termina en 503, no en 422


async def test_edad_y_sexo_son_opcionales(cliente_bd: httpx.AsyncClient) -> None:
    r = await _post(cliente_bd, _consulta())  # versiones anteriores de la app
    assert r.status_code != 422


async def test_sin_installation_id_responde_422(cliente_bd: httpx.AsyncClient) -> None:
    r = await cliente_bd.post("/v1/orientacion", json=_consulta())
    assert r.status_code == 422


async def test_sin_guias_cargadas_responde_503(cliente_bd: httpx.AsyncClient) -> None:
    r = await _post(cliente_bd, _consulta())
    assert r.status_code == 503
    assert r.json()["error"]["codigo"] == "orientacion_no_disponible"


async def test_mas_de_20_consultas_por_hora_responde_429(cliente_bd: httpx.AsyncClient) -> None:
    instalacion = uuid.uuid4()
    codigos = [
        (
            await cliente_bd.post(
                "/v1/orientacion", json=_consulta(), headers=cabeceras_app(instalacion)
            )
        ).status_code
        for _ in range(21)
    ]
    assert codigos[:20] == [503] * 20
    assert codigos[20] == 429
