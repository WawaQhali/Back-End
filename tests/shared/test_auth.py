"""JWT del medico, clave del servicio interno, X-Installation-Id y Argon2."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

import httpx
import pytest
from fastapi import Depends, FastAPI

from app.config import obtener_settings
from app.shared.auth import (
    Rol,
    Sesion,
    emitir_token,
    hashear_contrasena,
    id_instalacion,
    requiere_rol,
    requiere_servicio_interno,
    verificar_contrasena,
)
from app.shared.errores import registrar_manejadores
from tests.ayudas import cabeceras_rol_eliminado


def _app() -> FastAPI:
    app = FastAPI()
    registrar_manejadores(app)

    @app.get("/medico")
    async def solo_medico(
        sesion: Annotated[Sesion, Depends(requiere_rol(Rol.medico))],
    ) -> dict[str, str]:
        return {"usuario": sesion.usuario_id}

    @app.get("/interno", dependencies=[Depends(requiere_servicio_interno)])
    async def interno() -> dict[str, str]:
        return {"ok": "si"}

    @app.get("/app")
    async def app_movil(
        instalacion: Annotated[uuid.UUID, Depends(id_instalacion)],
    ) -> dict[str, str]:
        return {"instalacion": str(instalacion)}

    return app


@pytest.fixture
async def c():
    transporte = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transporte, base_url="http://prueba") as cliente:
        yield cliente


async def test_token_valido_con_rol_correcto(c: httpx.AsyncClient) -> None:
    token = emitir_token("u1", Rol.medico)
    r = await c.get("/medico", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json() == {"usuario": "u1"}


async def test_sin_token_responde_401(c: httpx.AsyncClient) -> None:
    r = await c.get("/medico")
    assert r.status_code == 401


def test_solo_existe_el_rol_medico() -> None:
    assert [r.value for r in Rol] == ["medico"]  # D39: se quito `equipo`


async def test_token_con_un_rol_que_ya_no_existe_responde_401(c: httpx.AsyncClient) -> None:
    r = await c.get("/medico", headers=cabeceras_rol_eliminado("equipo"))
    assert r.status_code == 401


async def test_token_vencido_responde_401(c: httpx.AsyncClient) -> None:
    hace_dos_horas = datetime.now(UTC) - timedelta(hours=2)
    token = emitir_token("u1", Rol.medico, ahora=hace_dos_horas)
    r = await c.get("/medico", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


async def test_token_con_otra_firma_responde_401(c: httpx.AsyncClient) -> None:
    import jwt

    falso = jwt.encode(
        {"sub": "u1", "rol": "medico", "exp": datetime.now(UTC) + timedelta(hours=1)},
        "otra-clave-que-no-es-la-del-servidor-1234567890",
        algorithm="HS256",
    )
    r = await c.get("/medico", headers={"Authorization": f"Bearer {falso}"})
    assert r.status_code == 401


async def test_clave_interna(c: httpx.AsyncClient) -> None:
    buena = obtener_settings().internal_api_key.get_secret_value()
    assert (await c.get("/interno", headers={"X-Api-Key": buena})).status_code == 200
    assert (await c.get("/interno", headers={"X-Api-Key": "mala"})).status_code == 401
    assert (await c.get("/interno")).status_code == 401


async def test_installation_id_debe_ser_uuid(c: httpx.AsyncClient) -> None:
    valido = str(uuid.uuid4())
    assert (await c.get("/app", headers={"X-Installation-Id": valido})).json() == {
        "instalacion": valido
    }
    assert (await c.get("/app", headers={"X-Installation-Id": "123"})).status_code == 422
    assert (await c.get("/app")).status_code == 422


def test_argon2() -> None:
    guardado = hashear_contrasena("una contrasena larga")
    assert guardado.startswith("$argon2")
    assert verificar_contrasena(guardado, "una contrasena larga")
    assert not verificar_contrasena(guardado, "otra")
    assert not verificar_contrasena("no-es-un-hash", "x")
