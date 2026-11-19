"""/health, OpenAPI, errores genericos, CORS y limite de tamano."""

import httpx
from fastapi import FastAPI
from pydantic import BaseModel

from app.shared.errores import ErrorApi, registrar_manejadores
from app.shared.limites import TAMANO_MAXIMO_BYTES, LimiteTamanoPeticion


async def test_health_responde_200_sin_autenticacion(cliente: httpx.AsyncClient) -> None:
    respuesta = await cliente.get("/health")
    assert respuesta.status_code == 200
    assert respuesta.json() == {"estado": "ok"}


async def test_openapi_lista_health(cliente: httpx.AsyncClient) -> None:
    respuesta = await cliente.get("/openapi.json")
    assert respuesta.status_code == 200
    assert "/health" in respuesta.json()["paths"]


async def test_ruta_inexistente_da_error_generico(cliente: httpx.AsyncClient) -> None:
    respuesta = await cliente.get("/v1/no-existe")
    assert respuesta.status_code == 404
    assert respuesta.json() == {"error": {"codigo": "no_encontrado", "mensaje": "No encontrado."}}


async def test_cors_solo_permite_la_app_web(cliente: httpx.AsyncClient) -> None:
    permitido = await cliente.options(
        "/health",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
    )
    ajeno = await cliente.options(
        "/health",
        headers={"Origin": "https://otro.example", "Access-Control-Request-Method": "GET"},
    )
    assert permitido.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert "access-control-allow-origin" not in ajeno.headers


async def test_peticion_de_mas_de_2_mb_responde_413(cliente: httpx.AsyncClient) -> None:
    respuesta = await cliente.post("/v1/donaciones", content=b"x" * (TAMANO_MAXIMO_BYTES + 1))
    assert respuesta.status_code == 413
    assert respuesta.json()["error"]["codigo"] == "peticion_muy_grande"


# --- App minima para probar los manejadores sin depender de endpoints reales ---


class _Entrada(BaseModel):
    texto_libre: str
    edad: int


def _app_de_prueba() -> FastAPI:
    app = FastAPI()
    registrar_manejadores(app)
    app.add_middleware(LimiteTamanoPeticion, maximo=100)

    @app.post("/eco")
    async def eco(entrada: _Entrada) -> dict[str, str]:
        return {"ok": "si"}

    @app.get("/falla")
    async def falla() -> None:
        raise RuntimeError("detalle interno secreto")

    @app.get("/prohibido")
    async def prohibido() -> None:
        raise ErrorApi(403, "sin_autorizacion", "No hay autorizacion vigente.")

    return app


def _cliente(app: FastAPI) -> httpx.AsyncClient:
    transporte = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transporte, base_url="http://prueba")


async def test_error_de_validacion_no_devuelve_los_valores_recibidos() -> None:
    async with _cliente(_app_de_prueba()) as c:
        respuesta = await c.post("/eco", json={"texto_libre": "SINTOMA-PRIVADO", "edad": "x"})
    assert respuesta.status_code == 422
    assert "SINTOMA-PRIVADO" not in respuesta.text
    assert respuesta.json()["error"]["campos"] == ["body.edad"]


async def test_error_inesperado_no_filtra_el_detalle(caplog) -> None:  # noqa: ANN001
    async with _cliente(_app_de_prueba()) as c:
        respuesta = await c.get("/falla")
    assert respuesta.status_code == 500
    assert "secreto" not in respuesta.text
    assert respuesta.json()["error"]["codigo"] == "error_interno"


async def test_error_api_se_devuelve_con_su_codigo() -> None:
    async with _cliente(_app_de_prueba()) as c:
        respuesta = await c.get("/prohibido")
    assert respuesta.status_code == 403
    assert respuesta.json()["error"]["codigo"] == "sin_autorizacion"


async def test_cuerpo_sin_content_length_que_excede_responde_413() -> None:
    async def trozos():
        for _ in range(5):
            yield b"y" * 50

    async with _cliente(_app_de_prueba()) as c:
        respuesta = await c.post("/eco", content=trozos())
    assert respuesta.status_code == 413
