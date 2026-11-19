"""Recepcion: clave publica, validacion de paquetes, autorizacion y revocacion (OE4-I4)."""

import base64
import json
import os
import uuid

import httpx
import pytest
from sqlalchemy import select

from app.modules.recepcion.tablas import Paquete
from tests.ayudas import armar_paquete, cabeceras_app, contenido_donado

pytestmark = pytest.mark.bd


@pytest.fixture
async def jwk(cliente_bd: httpx.AsyncClient) -> dict:
    r = await cliente_bd.get("/v1/claves/publica", headers=cabeceras_app(uuid.uuid4()))
    assert r.status_code == 200
    return r.json()


async def _autorizar(cliente: httpx.AsyncClient, instalacion: uuid.UUID) -> None:
    r = await cliente.post(
        "/v1/autorizaciones",
        json={"installation_id": str(instalacion), "version_texto": "v1"},
        headers=cabeceras_app(instalacion),
    )
    assert r.status_code == 201


async def _donar(cliente: httpx.AsyncClient, instalacion: uuid.UUID, paquete: dict):  # noqa: ANN202
    return await cliente.post("/v1/donaciones", json=paquete, headers=cabeceras_app(instalacion))


def _b64(n: int) -> str:
    return base64.b64encode(os.urandom(n)).decode()


async def test_clave_publica_es_un_jwk_rsa_oaep_256(jwk: dict) -> None:
    assert set(jwk) == {"kty", "n", "e", "kid", "alg"}
    assert (jwk["kty"], jwk["alg"]) == ("RSA", "RSA-OAEP-256")


async def test_sin_autorizacion_vigente_responde_403(
    cliente_bd: httpx.AsyncClient, jwk: dict
) -> None:
    instalacion = uuid.uuid4()
    r = await _donar(cliente_bd, instalacion, armar_paquete(jwk, instalacion, contenido_donado()))
    assert r.status_code == 403
    assert r.json()["error"]["codigo"] == "sin_autorizacion"


async def test_paquete_valido_queda_en_cuarentena_tal_cual(
    cliente_bd: httpx.AsyncClient,
    jwk: dict,
    blob,
    sesionador,  # noqa: ANN001
) -> None:
    instalacion = uuid.uuid4()
    await _autorizar(cliente_bd, instalacion)
    paquete = armar_paquete(jwk, instalacion, contenido_donado())

    r = await _donar(cliente_bd, instalacion, paquete)

    assert r.status_code == 202
    id_paquete = r.json()["id"]
    ruta = f"cuarentena/{instalacion}/{id_paquete}.json"
    assert json.loads(blob.blobs[ruta]) == paquete
    async with sesionador() as s:
        fila = await s.get(Paquete, uuid.UUID(id_paquete))
    assert fila is not None
    assert (fila.blob_path, fila.kid, fila.eliminado_en) == (ruta, jwk["kid"], None)


@pytest.mark.parametrize(
    ("cambio", "codigo"),
    [
        pytest.param({"kid": "https://otro.vault/keys/x/1"}, "kid_desconocido", id="kid"),
        pytest.param({"clave_cifrada": None}, "tamano_invalido", id="clave_256_bytes"),
        pytest.param({"nonce": None}, "tamano_invalido", id="nonce_16_bytes"),
        pytest.param({"datos": None}, "tamano_invalido", id="datos_cortos"),
        pytest.param({"nonce": "no*es*base64"}, "base64_invalido", id="base64"),
        pytest.param({"v": 2}, "version_no_soportada", id="version"),
        pytest.param({"alg": "RSA1_5+A128CBC"}, "algoritmo_no_soportado", id="alg"),
    ],
)
async def test_paquetes_con_formato_invalido_responden_422(
    cliente_bd: httpx.AsyncClient,
    jwk: dict,
    blob,
    cambio: dict,
    codigo: str,  # noqa: ANN001
) -> None:
    tamanos_malos = {"clave_cifrada": _b64(256), "nonce": _b64(16), "datos": _b64(10)}
    instalacion = uuid.uuid4()
    await _autorizar(cliente_bd, instalacion)
    paquete = armar_paquete(jwk, instalacion, contenido_donado())
    paquete.update({k: (tamanos_malos[k] if v is None else v) for k, v in cambio.items()})

    r = await _donar(cliente_bd, instalacion, paquete)

    assert r.status_code == 422
    assert r.json()["error"]["codigo"] == codigo
    assert blob.blobs == {}


async def test_campo_extra_o_faltante_responde_422(
    cliente_bd: httpx.AsyncClient, jwk: dict
) -> None:
    instalacion = uuid.uuid4()
    await _autorizar(cliente_bd, instalacion)
    paquete = armar_paquete(jwk, instalacion, contenido_donado())
    assert (await _donar(cliente_bd, instalacion, {**paquete, "extra": 1})).status_code == 422
    del paquete["nonce"]
    assert (await _donar(cliente_bd, instalacion, paquete)).status_code == 422


async def test_paquete_de_mas_de_2_mb_responde_413(
    cliente_bd: httpx.AsyncClient, jwk: dict
) -> None:
    instalacion = uuid.uuid4()
    await _autorizar(cliente_bd, instalacion)
    paquete = armar_paquete(jwk, instalacion, contenido_donado(b"\xff" * (2 * 1024 * 1024)))
    assert (await _donar(cliente_bd, instalacion, paquete)).status_code == 413


async def test_revocar_borra_los_paquetes_en_cuarentena(
    cliente_bd: httpx.AsyncClient,
    jwk: dict,
    blob,
    sesionador,  # noqa: ANN001
) -> None:
    instalacion, otra = uuid.uuid4(), uuid.uuid4()
    for i in (instalacion, instalacion, otra):
        await _autorizar(cliente_bd, i)
        r = await _donar(cliente_bd, i, armar_paquete(jwk, i, contenido_donado()))
        assert r.status_code == 202
    assert len(blob.blobs) == 3

    r = await cliente_bd.delete(
        f"/v1/autorizaciones/{instalacion}", headers=cabeceras_app(instalacion)
    )
    assert r.status_code == 204

    assert list(blob.blobs) == [p for p in blob.blobs if str(otra) in p]  # solo queda la otra
    async with sesionador() as s:
        filas = (await s.execute(select(Paquete))).scalars().all()
    borrados = {f.installation_id: f.eliminado_en is not None for f in filas}
    assert borrados == {instalacion: True, otra: False}

    # Y ya no puede donar
    r = await _donar(cliente_bd, instalacion, armar_paquete(jwk, instalacion, contenido_donado()))
    assert r.status_code == 403


async def test_mas_de_10_donaciones_por_hora_responde_429(
    cliente_bd: httpx.AsyncClient, jwk: dict
) -> None:
    instalacion = uuid.uuid4()
    await _autorizar(cliente_bd, instalacion)
    codigos = [
        (
            await _donar(
                cliente_bd, instalacion, armar_paquete(jwk, instalacion, contenido_donado())
            )
        ).status_code
        for _ in range(11)
    ]
    assert codigos == [202] * 10 + [429]
