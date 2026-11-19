"""Revision: login, app web del medico, endpoints internos y revocacion (OE4-I4)."""

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select

from app.config import obtener_settings
from app.modules.revision.servicio import crear_usuario
from app.modules.revision.tablas import Imagen, Usuario
from app.shared.auth import Rol
from tests.ayudas import RESPUESTAS_V1, cabeceras_app, cabeceras_rol

pytestmark = pytest.mark.bd

MEDICO = cabeceras_rol(Rol.medico)
INTERNO_FALTA = {"X-Api-Key": "x" * 40}


def _interno() -> dict[str, str]:
    return {"X-Api-Key": obtener_settings().internal_api_key.get_secret_value()}


def _verificada(instalacion: uuid.UUID | None = None, clase: str = "compatible") -> dict:
    paquete = uuid.uuid4()
    return {
        "paquete_id": str(paquete),
        "installation_id": str(instalacion or uuid.uuid4()),
        "blob_path": f"verificadas/{paquete}.jpg",
        "etiqueta_preliminar": {
            "clase": clase,
            "confianza": 0.88,
            "respuestas": RESPUESTAS_V1,
            "version_modelo": "1.0.0",
            "version_cuestionario": "v1",
        },
    }


async def _registrar(cliente: httpx.AsyncClient, datos: dict, blob) -> str:  # noqa: ANN001
    await blob.subir(datos["blob_path"], b"jpeg", "image/jpeg")
    r = await cliente.post("/v1/interno/revision/verificadas", json=datos, headers=_interno())
    assert r.status_code == 201
    return r.json()["id"]


# --- Login ----------------------------------------------------------------------------


@pytest.fixture
async def cuenta(sesionador) -> tuple[str, str]:  # noqa: ANN001
    async with sesionador() as s:
        await crear_usuario(s, "dra.prueba", "una-contrasena-larga", Rol.medico)
    return "dra.prueba", "una-contrasena-larga"


async def _login(cliente: httpx.AsyncClient, usuario: str, contrasena: str) -> httpx.Response:
    return await cliente.post("/v1/auth/login", json={"usuario": usuario, "contrasena": contrasena})


async def test_login_correcto_da_un_jwt_que_sirve(
    cliente_bd: httpx.AsyncClient, cuenta: tuple[str, str]
) -> None:
    r = await _login(cliente_bd, *cuenta)
    assert r.status_code == 200
    token = r.json()
    assert (token["token_type"], token["expira_en"], token["rol"]) == ("bearer", 3600, "medico")
    cabecera = {"Authorization": f"Bearer {token['access_token']}"}
    assert (await cliente_bd.get("/v1/revision/pendientes", headers=cabecera)).status_code == 200


async def test_login_incorrecto_o_inactivo_responde_401_igual(
    cliente_bd: httpx.AsyncClient,
    cuenta: tuple[str, str],
    sesionador,  # noqa: ANN001
) -> None:
    usuario, contrasena = cuenta
    mala = await _login(cliente_bd, usuario, "otra")
    inexistente = await _login(cliente_bd, "nadie", contrasena)
    assert mala.status_code == inexistente.status_code == 401
    assert mala.json() == inexistente.json()  # no revela que usuarios existen

    async with sesionador() as s, s.begin():
        fila = (await s.execute(select(Usuario))).scalar_one()
        fila.activo = False
    assert (await _login(cliente_bd, usuario, contrasena)).status_code == 401


async def test_contrasena_guardada_con_argon2(cuenta: tuple[str, str], sesionador) -> None:  # noqa: ANN001
    async with sesionador() as s:
        fila = (await s.execute(select(Usuario))).scalar_one()
    assert fila.hash_contrasena.startswith("$argon2")
    assert cuenta[1] not in fila.hash_contrasena


async def test_mas_de_5_logins_por_minuto_responde_429(
    cliente_bd: httpx.AsyncClient, cuenta: tuple[str, str]
) -> None:
    codigos = [(await _login(cliente_bd, cuenta[0], "mala")).status_code for _ in range(6)]
    assert codigos == [401] * 5 + [429]


# --- App web del medico --------------------------------------------------------------------


async def test_solo_el_medico_ve_las_pendientes(cliente_bd: httpx.AsyncClient) -> None:
    assert (await cliente_bd.get("/v1/revision/pendientes")).status_code == 401
    equipo = cabeceras_rol(Rol.equipo)
    assert (await cliente_bd.get("/v1/revision/pendientes", headers=equipo)).status_code == 403


async def test_pendientes_paginadas_de_la_mas_antigua_a_la_mas_nueva(
    cliente_bd: httpx.AsyncClient,
    blob,  # noqa: ANN001
) -> None:
    ids = [await _registrar(cliente_bd, _verificada(), blob) for _ in range(3)]

    pagina1 = (await cliente_bd.get("/v1/revision/pendientes?tamano=2", headers=MEDICO)).json()
    pagina2 = (
        await cliente_bd.get("/v1/revision/pendientes?tamano=2&pagina=2", headers=MEDICO)
    ).json()

    assert pagina1["total"] == 3
    assert [i["id"] for i in pagina1["items"] + pagina2["items"]] == ids
    assert pagina1["items"][0]["clase"] == "compatible"


async def test_detalle_trae_la_etiqueta_preliminar_y_un_enlace_temporal(
    cliente_bd: httpx.AsyncClient,
    blob,  # noqa: ANN001
) -> None:
    datos = _verificada()
    id_imagen = await _registrar(cliente_bd, datos, blob)
    r = await cliente_bd.get(f"/v1/revision/{id_imagen}", headers=MEDICO)
    assert r.status_code == 200
    detalle = r.json()
    assert detalle["etiqueta_preliminar"]["respuestas"] == RESPUESTAS_V1
    assert detalle["url"].startswith(f"memoria://{datos['blob_path']}?se=")
    assert detalle["estado"] == "pendiente"


async def test_etiquetar_saca_la_imagen_de_pendientes_y_se_puede_corregir(
    cliente_bd: httpx.AsyncClient,
    blob,  # noqa: ANN001
) -> None:
    id_imagen = await _registrar(cliente_bd, _verificada(), blob)
    url = f"/v1/revision/{id_imagen}/etiqueta"

    r = await cliente_bd.post(url, json={"etiqueta": "no_compatible"}, headers=MEDICO)
    assert r.status_code == 204
    assert (await cliente_bd.get("/v1/revision/pendientes", headers=MEDICO)).json()["total"] == 0

    r = await cliente_bd.post(
        url, json={"etiqueta": "compatible", "comentario": "Habones tipicos"}, headers=MEDICO
    )
    assert r.status_code == 204
    detalle = (await cliente_bd.get(f"/v1/revision/{id_imagen}", headers=MEDICO)).json()
    assert (detalle["etiqueta_final"], detalle["comentario"]) == ("compatible", "Habones tipicos")


async def test_etiqueta_invalida_responde_422(cliente_bd: httpx.AsyncClient, blob) -> None:  # noqa: ANN001
    id_imagen = await _registrar(cliente_bd, _verificada(), blob)
    r = await cliente_bd.post(
        f"/v1/revision/{id_imagen}/etiqueta", json={"etiqueta": "quiza"}, headers=MEDICO
    )
    assert r.status_code == 422


async def test_eliminar_borra_el_blob_y_la_oculta(cliente_bd: httpx.AsyncClient, blob) -> None:  # noqa: ANN001
    datos = _verificada()
    id_imagen = await _registrar(cliente_bd, datos, blob)

    r = await cliente_bd.post(f"/v1/revision/{id_imagen}/eliminar", headers=MEDICO)

    assert r.status_code == 204
    assert datos["blob_path"] not in blob.blobs
    assert (await cliente_bd.get(f"/v1/revision/{id_imagen}", headers=MEDICO)).status_code == 404
    assert (await cliente_bd.get("/v1/revision/pendientes", headers=MEDICO)).json()["total"] == 0


async def test_imagen_inexistente_responde_404(cliente_bd: httpx.AsyncClient) -> None:
    r = await cliente_bd.get(f"/v1/revision/{uuid.uuid4()}", headers=MEDICO)
    assert r.status_code == 404


# --- Endpoints internos ------------------------------------------------------------------------


async def test_internos_exigen_la_clave_del_servicio(cliente_bd: httpx.AsyncClient) -> None:
    r = await cliente_bd.post("/v1/interno/revision/verificadas", json=_verificada())
    assert r.status_code == 401
    r = await cliente_bd.post(
        "/v1/interno/revision/verificadas", json=_verificada(), headers=INTERNO_FALTA
    )
    assert r.status_code == 401
    # Un medico tampoco entra a las rutas internas
    r = await cliente_bd.get(
        "/v1/interno/revision/etiquetas?desde=2026-01-01T00:00:00Z", headers=MEDICO
    )
    assert r.status_code == 401


async def test_mismo_paquete_dos_veces_responde_409(cliente_bd: httpx.AsyncClient, blob) -> None:  # noqa: ANN001
    datos = _verificada()
    await _registrar(cliente_bd, datos, blob)
    r = await cliente_bd.post("/v1/interno/revision/verificadas", json=datos, headers=_interno())
    assert r.status_code == 409


async def test_etiquetas_desde_una_fecha(cliente_bd: httpx.AsyncClient, blob) -> None:  # noqa: ANN001
    antes = datetime.now(UTC) - timedelta(seconds=1)
    etiquetada = await _registrar(cliente_bd, _verificada(), blob)
    await _registrar(cliente_bd, _verificada(), blob)  # queda pendiente
    await cliente_bd.post(
        f"/v1/revision/{etiquetada}/etiqueta", json={"etiqueta": "compatible"}, headers=MEDICO
    )

    r = await cliente_bd.get(
        "/v1/interno/revision/etiquetas", params={"desde": antes.isoformat()}, headers=_interno()
    )
    assert r.status_code == 200
    assert [(e["id"], e["etiqueta_final"]) for e in r.json()] == [(etiquetada, "compatible")]

    despues = (datetime.now(UTC) + timedelta(minutes=1)).isoformat()
    r = await cliente_bd.get(
        "/v1/interno/revision/etiquetas", params={"desde": despues}, headers=_interno()
    )
    assert r.json() == []


async def test_imagen_usada_en_un_modelo_ya_no_se_puede_reetiquetar(
    cliente_bd: httpx.AsyncClient,
    blob,  # noqa: ANN001
) -> None:
    id_imagen = await _registrar(cliente_bd, _verificada(), blob)
    url = f"/v1/revision/{id_imagen}/etiqueta"
    await cliente_bd.post(url, json={"etiqueta": "compatible"}, headers=MEDICO)
    r = await cliente_bd.post(
        "/v1/interno/revision/usadas",
        json={"version_modelo": "1.1.0", "ids": [id_imagen]},
        headers=_interno(),
    )
    assert r.json() == {"marcadas": 1}
    assert (
        await cliente_bd.post(url, json={"etiqueta": "no_compatible"}, headers=MEDICO)
    ).status_code == 409


# --- Revocacion --------------------------------------------------------------------------------


async def test_revocar_borra_las_imagenes_no_usadas_y_conserva_las_usadas(
    cliente_bd: httpx.AsyncClient,
    blob,
    sesionador,  # noqa: ANN001
) -> None:
    instalacion = uuid.uuid4()
    await cliente_bd.post(
        "/v1/autorizaciones",
        json={"installation_id": str(instalacion), "version_texto": "v1"},
        headers=cabeceras_app(instalacion),
    )
    usada_datos, no_usada_datos, ajena_datos = (
        _verificada(instalacion),
        _verificada(instalacion),
        _verificada(),
    )
    usada = await _registrar(cliente_bd, usada_datos, blob)
    await _registrar(cliente_bd, no_usada_datos, blob)
    ajena = await _registrar(cliente_bd, ajena_datos, blob)
    await cliente_bd.post(
        f"/v1/revision/{usada}/etiqueta", json={"etiqueta": "compatible"}, headers=MEDICO
    )
    await cliente_bd.post(
        "/v1/interno/revision/usadas",
        json={"version_modelo": "1.1.0", "ids": [usada]},
        headers=_interno(),
    )

    r = await cliente_bd.delete(
        f"/v1/autorizaciones/{instalacion}", headers=cabeceras_app(instalacion)
    )
    assert r.status_code == 204

    async with sesionador() as s:
        quedan = {str(f.id) for f in (await s.execute(select(Imagen))).scalars().all()}
    assert quedan == {usada, ajena}
    assert no_usada_datos["blob_path"] not in blob.blobs
    assert usada_datos["blob_path"] in blob.blobs
