"""Autorizacion: registrar, consultar y revocar."""

import uuid

import httpx
import pytest
from sqlalchemy import select

from app.shared.eventos import EventoFila
from tests.ayudas import cabeceras_app

pytestmark = pytest.mark.bd


async def _otorgar(cliente: httpx.AsyncClient, instalacion: uuid.UUID) -> httpx.Response:
    return await cliente.post(
        "/v1/autorizaciones",
        json={"installation_id": str(instalacion), "version_texto": "v1"},
        headers=cabeceras_app(instalacion),
    )


async def test_registrar_consultar_y_revocar(cliente_bd: httpx.AsyncClient) -> None:
    instalacion = uuid.uuid4()
    r = await _otorgar(cliente_bd, instalacion)
    assert r.status_code == 201
    assert r.json()["estado"] == "vigente"

    url = f"/v1/autorizaciones/{instalacion}"
    assert (await cliente_bd.get(url, headers=cabeceras_app(instalacion))).json()[
        "estado"
    ] == "vigente"

    r = await cliente_bd.delete(url, headers=cabeceras_app(instalacion))
    assert r.status_code == 204
    estado = (await cliente_bd.get(url, headers=cabeceras_app(instalacion))).json()
    assert estado["estado"] == "revocada"
    assert estado["revocada_en"] is not None


async def test_revocar_publica_un_solo_evento_aunque_se_repita(
    cliente_bd: httpx.AsyncClient,
    sesionador,  # noqa: ANN001
) -> None:
    instalacion = uuid.uuid4()
    await _otorgar(cliente_bd, instalacion)
    url = f"/v1/autorizaciones/{instalacion}"
    assert (await cliente_bd.delete(url, headers=cabeceras_app(instalacion))).status_code == 204
    assert (await cliente_bd.delete(url, headers=cabeceras_app(instalacion))).status_code == 204

    async with sesionador() as s:
        eventos = (await s.execute(select(EventoFila))).scalars().all()
    assert [e.tipo for e in eventos] == ["AutorizacionRevocada"]
    assert eventos[0].payload == {"installation_id": str(instalacion)}
    # Recepcion y Revision ya lo procesaron (tarea en segundo plano tras el 204)
    assert set(eventos[0].procesado_por) == {"recepcion", "revision"}


async def test_volver_a_autorizar_tras_revocar(cliente_bd: httpx.AsyncClient) -> None:
    instalacion = uuid.uuid4()
    await _otorgar(cliente_bd, instalacion)
    await cliente_bd.delete(f"/v1/autorizaciones/{instalacion}", headers=cabeceras_app(instalacion))
    r = await _otorgar(cliente_bd, instalacion)
    assert r.json()["estado"] == "vigente"
    assert r.json()["revocada_en"] is None


async def test_no_se_puede_gestionar_otra_instalacion(cliente_bd: httpx.AsyncClient) -> None:
    mia, ajena = uuid.uuid4(), uuid.uuid4()
    await _otorgar(cliente_bd, ajena)
    r = await cliente_bd.delete(f"/v1/autorizaciones/{ajena}", headers=cabeceras_app(mia))
    assert r.status_code == 403
    r = await cliente_bd.post(
        "/v1/autorizaciones",
        json={"installation_id": str(ajena), "version_texto": "v1"},
        headers=cabeceras_app(mia),
    )
    assert r.status_code == 403


async def test_consultar_sin_registro_responde_404(cliente_bd: httpx.AsyncClient) -> None:
    instalacion = uuid.uuid4()
    r = await cliente_bd.get(
        f"/v1/autorizaciones/{instalacion}", headers=cabeceras_app(instalacion)
    )
    assert r.status_code == 404
