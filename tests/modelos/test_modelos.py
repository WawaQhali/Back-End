"""Modelos: candidatos, compuerta de sensibilidad, manifiesto y reversion (OE4-I4)."""

import uuid

import httpx
import pytest

from app.config import obtener_settings
from app.shared.auth import Rol
from tests.ayudas import cabeceras_app, cabeceras_rol

pytestmark = pytest.mark.bd

EQUIPO = cabeceras_rol(Rol.equipo)


def _interno() -> dict[str, str]:
    return {"X-Api-Key": obtener_settings().internal_api_key.get_secret_value()}


def _candidato(version: str, sensibilidad: float, **cambios) -> dict:  # noqa: ANN003
    base = {
        "version": version,
        "sensibilidad": sensibilidad,
        "blob_path": f"modelos/{version}/modelo.tflite",
        "sha256": "ab" * 32,
        "tamano": 3240392,
        "entrada": {"ancho": 224, "alto": 224, "canales": 3, "normalizacion": "0_255"},
        "clases": ["compatible", "no_compatible"],
        "umbral_confianza": 0.6,
    }
    return {**base, **cambios}


async def _registrar(cliente: httpx.AsyncClient, candidato: dict) -> httpx.Response:
    return await cliente.post("/v1/interno/modelos/candidatos", json=candidato, headers=_interno())


async def _publicar(cliente: httpx.AsyncClient, version: str) -> httpx.Response:
    return await cliente.post(f"/v1/modelos/{version}/publicar", headers=EQUIPO)


async def _manifiesto(cliente: httpx.AsyncClient) -> httpx.Response:
    return await cliente.get("/v1/modelos/manifiesto", headers=cabeceras_app(uuid.uuid4()))


async def _publicar_vigente(cliente: httpx.AsyncClient, version: str = "1.0.0") -> None:
    assert (await _registrar(cliente, _candidato(version, 0.90))).status_code == 201
    assert (await _publicar(cliente, version)).status_code == 200


async def test_sin_modelo_publicado_el_manifiesto_responde_404(
    cliente_bd: httpx.AsyncClient,
) -> None:
    assert (await _manifiesto(cliente_bd)).status_code == 404


async def test_publicar_y_leer_el_manifiesto(cliente_bd: httpx.AsyncClient) -> None:
    await _publicar_vigente(cliente_bd)
    r = await _manifiesto(cliente_bd)
    assert r.status_code == 200
    m = r.json()
    assert (m["version"], m["tamano"], m["clases"]) == (
        "1.0.0",
        3240392,
        ["compatible", "no_compatible"],
    )
    assert m["entrada"]["ancho"] == 224
    assert m["url"].startswith("memoria://modelos/1.0.0/modelo.tflite?se=")
    assert "sp=r" in m["url"]


async def test_compuerta_rechaza_menor_sensibilidad_y_el_vigente_no_cambia(
    cliente_bd: httpx.AsyncClient,
) -> None:
    await _publicar_vigente(cliente_bd)
    await _registrar(cliente_bd, _candidato("1.1.0", 0.85))

    r = await _publicar(cliente_bd, "1.1.0")

    assert r.status_code == 409
    assert r.json()["error"]["codigo"] == "compuerta_rechazada"
    assert (await _manifiesto(cliente_bd)).json()["version"] == "1.0.0"
    # Queda bloqueado: no se puede volver a intentar
    assert (await _publicar(cliente_bd, "1.1.0")).json()["error"]["codigo"] == "no_es_candidato"


@pytest.mark.parametrize(
    "cambio",
    [
        pytest.param({"clases": ["no_compatible", "compatible"]}, id="orden_de_clases"),
        pytest.param({"clases": ["compatible", "no_compatible", "indeterminado"]}, id="clases"),
        pytest.param(
            {"entrada": {"ancho": 256, "alto": 256, "canales": 3, "normalizacion": "0_255"}},
            id="tamano_de_entrada",
        ),
    ],
)
async def test_compuerta_rechaza_cambios_de_contrato(
    cliente_bd: httpx.AsyncClient, cambio: dict
) -> None:
    await _publicar_vigente(cliente_bd)
    await _registrar(cliente_bd, _candidato("1.1.0", 0.95, **cambio))
    assert (await _publicar(cliente_bd, "1.1.0")).status_code == 409
    assert (await _manifiesto(cliente_bd)).json()["version"] == "1.0.0"


async def test_igual_o_mayor_sensibilidad_se_publica_y_el_anterior_se_retira(
    cliente_bd: httpx.AsyncClient,
) -> None:
    await _publicar_vigente(cliente_bd)
    await _registrar(cliente_bd, _candidato("1.1.0", 0.90))  # igual tambien pasa
    r = await _publicar(cliente_bd, "1.1.0")
    assert r.status_code == 200
    assert r.json()["estado"] == "publicado"
    assert (await _manifiesto(cliente_bd)).json()["version"] == "1.1.0"


async def test_revertir_vuelve_a_la_version_anterior(cliente_bd: httpx.AsyncClient) -> None:
    await _publicar_vigente(cliente_bd, "1.0.0")
    await _registrar(cliente_bd, _candidato("1.1.0", 0.93))
    await _publicar(cliente_bd, "1.1.0")

    r = await cliente_bd.post("/v1/modelos/1.1.0/revertir", headers=EQUIPO)

    assert r.status_code == 200
    assert r.json()["version"] == "1.0.0"
    assert (await _manifiesto(cliente_bd)).json()["version"] == "1.0.0"
    # 1.0.0 no tiene anterior
    r = await cliente_bd.post("/v1/modelos/1.0.0/revertir", headers=EQUIPO)
    assert r.json()["error"]["codigo"] == "sin_anterior"


async def test_permisos(cliente_bd: httpx.AsyncClient) -> None:
    sin_clave = await cliente_bd.post(
        "/v1/interno/modelos/candidatos", json=_candidato("1.0.0", 0.9)
    )
    assert sin_clave.status_code == 401
    await _registrar(cliente_bd, _candidato("1.0.0", 0.9))
    medico = cabeceras_rol(Rol.medico)
    assert (await cliente_bd.post("/v1/modelos/1.0.0/publicar", headers=medico)).status_code == 403
    assert (await cliente_bd.post("/v1/modelos/1.0.0/publicar")).status_code == 401


async def test_version_repetida_responde_409(cliente_bd: httpx.AsyncClient) -> None:
    assert (await _registrar(cliente_bd, _candidato("1.0.0", 0.9))).status_code == 201
    assert (await _registrar(cliente_bd, _candidato("1.0.0", 0.9))).status_code == 409


async def test_candidato_con_formato_invalido_responde_422(cliente_bd: httpx.AsyncClient) -> None:
    for malo in (
        _candidato("v1", 0.9),
        _candidato("1.0.0", 1.5),
        _candidato("1.0.0", 0.9, sha256="xyz"),
        _candidato("1.0.0", 0.9, blob_path="cuarentena/x.tflite"),
        _candidato("1.0.0", 0.9, clases=["a", "a"]),
    ):
        assert (await _registrar(cliente_bd, malo)).status_code == 422
