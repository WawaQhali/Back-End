"""Prueba completa del pipeline de donacion (etapa 4), con los proveedores falsos:

app movil  -> autoriza, pide la clave publica, cifra y dona
reentrenamiento -> lee la cuarentena, descifra (6.4), verifica y registra en Revision
medico     -> login, ve la pendiente, abre el detalle y etiqueta
reentrenamiento -> lee las etiquetas finales y las marca como usadas
"""

import base64
import json
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.config import obtener_settings
from app.modules.revision.servicio import crear_usuario
from app.shared.auth import Rol
from tests.ayudas import armar_paquete, cabeceras_app, contenido_donado, descifrar_paquete

pytestmark = pytest.mark.bd

# Cabecera y cola de un JPEG; en la prueba real del informe se usan imagenes publicas.
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 2048 + b"\xff\xd9"


async def test_pipeline_completo_de_donacion_a_etiqueta(
    cliente_bd: httpx.AsyncClient,
    blob,
    claves,
    sesionador,  # noqa: ANN001
) -> None:
    inicio = datetime.now(UTC) - timedelta(seconds=1)
    instalacion = uuid.uuid4()
    app = cabeceras_app(instalacion)
    interno = {"X-Api-Key": obtener_settings().internal_api_key.get_secret_value()}

    # 1. App movil: autoriza, pide la clave y dona la imagen cifrada
    r = await cliente_bd.post(
        "/v1/autorizaciones",
        json={"installation_id": str(instalacion), "version_texto": "v1"},
        headers=app,
    )
    assert r.status_code == 201
    jwk = (await cliente_bd.get("/v1/claves/publica", headers=app)).json()
    contenido = contenido_donado(JPEG)
    r = await cliente_bd.post(
        "/v1/donaciones", json=armar_paquete(jwk, instalacion, contenido), headers=app
    )
    assert r.status_code == 202
    id_paquete = r.json()["id"]

    # 2. Reentrenamiento: descifra desde la cuarentena y registra la imagen verificada
    en_cuarentena = json.loads(blob.blobs[f"cuarentena/{instalacion}/{id_paquete}.json"])
    claro = descifrar_paquete(en_cuarentena, instalacion, claves)
    imagen = base64.b64decode(claro["imagen_jpeg"])
    assert imagen == JPEG
    ruta_verificada = f"verificadas/{id_paquete}.jpg"
    await blob.subir(ruta_verificada, imagen, "image/jpeg")
    r = await cliente_bd.post(
        "/v1/interno/revision/verificadas",
        json={
            "paquete_id": id_paquete,
            "installation_id": str(instalacion),
            "blob_path": ruta_verificada,
            "etiqueta_preliminar": claro["etiqueta_preliminar"],
        },
        headers=interno,
    )
    assert r.status_code == 201
    id_imagen = r.json()["id"]

    # 3. Medico: login, pendientes, detalle y etiqueta
    async with sesionador() as s:
        await crear_usuario(s, "dra.pipeline", "contrasena-de-prueba", Rol.medico)
    token = (
        await cliente_bd.post(
            "/v1/auth/login", json={"usuario": "dra.pipeline", "contrasena": "contrasena-de-prueba"}
        )
    ).json()["access_token"]
    medico = {"Authorization": f"Bearer {token}"}

    pendientes = (await cliente_bd.get("/v1/revision/pendientes", headers=medico)).json()
    assert [i["id"] for i in pendientes["items"]] == [id_imagen]
    detalle = (await cliente_bd.get(f"/v1/revision/{id_imagen}", headers=medico)).json()
    assert detalle["etiqueta_preliminar"]["clase"] == "compatible"
    assert detalle["url"].startswith(f"memoria://{ruta_verificada}")
    r = await cliente_bd.post(
        f"/v1/revision/{id_imagen}/etiqueta", json={"etiqueta": "compatible"}, headers=medico
    )
    assert r.status_code == 204

    # 4. Reentrenamiento: lee las etiquetas finales y marca la imagen como usada
    etiquetas = (
        await cliente_bd.get(
            "/v1/interno/revision/etiquetas", params={"desde": inicio.isoformat()}, headers=interno
        )
    ).json()
    assert [(e["id"], e["etiqueta_final"], e["blob_path"]) for e in etiquetas] == [
        (id_imagen, "compatible", ruta_verificada)
    ]
    r = await cliente_bd.post(
        "/v1/interno/revision/usadas",
        json={"version_modelo": "1.1.0", "ids": [id_imagen]},
        headers=interno,
    )
    assert r.json() == {"marcadas": 1}
