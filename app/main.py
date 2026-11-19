"""Crea la app, monta los routers de los modulos y expone /health."""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import obtener_settings
from app.modules import autorizacion, modelos, orientacion, recepcion, revision
from app.shared.db import obtener_engine, obtener_sesionador
from app.shared.errores import registrar_manejadores
from app.shared.eventos import bus
from app.shared.limites import LimiteTamanoPeticion, limitador
from app.shared.logs import configurar_logs
from app.shared.puertos import registrar_puerto_autorizacion

log = logging.getLogger(__name__)

MODULOS = (autorizacion, recepcion, revision, orientacion, modelos)
INTERVALO_EVENTOS_S = 60


async def _ciclo_eventos() -> None:
    """Procesa eventos pendientes al arrancar y luego cada minuto (seccion 3)."""
    while True:
        try:
            await bus.procesar_pendientes(obtener_sesionador())
        except Exception as error:  # la BD puede no estar lista todavia
            log.warning("No se pudieron procesar eventos: %s", type(error).__name__)
        await asyncio.sleep(INTERVALO_EVENTOS_S)


async def _crear_cuenta_fija() -> None:
    try:
        await revision.asegurar_cuenta_fija(obtener_sesionador())
    except Exception as error:  # la BD puede no estar migrada todavia
        log.warning("No se pudo crear la cuenta fija del medico: %s", type(error).__name__)


@contextlib.asynccontextmanager
async def _ciclo_de_vida(_: FastAPI) -> AsyncIterator[None]:
    await _crear_cuenta_fija()
    tarea = asyncio.create_task(_ciclo_eventos())
    try:
        yield
    finally:
        tarea.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await tarea
        await obtener_engine().dispose()


def crear_app() -> FastAPI:
    settings = obtener_settings()
    configurar_logs(settings.log_level)

    app = FastAPI(
        title="Wawa Qhali API",
        version="0.1.0",
        description="Backend de Wawa Qhali. Ver wawa-qhali-backend.md.",
        lifespan=_ciclo_de_vida,
    )
    app.state.limiter = limitador
    registrar_manejadores(app)

    # El ultimo agregado es el mas externo: CORS envuelve todo, incluso los 413.
    app.add_middleware(LimiteTamanoPeticion)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.get("/health", tags=["salud"], summary="El contenedor esta vivo")
    async def health() -> dict[str, str]:
        # No toca servicios externos (seccion 10).
        return {"estado": "ok"}

    for modulo in MODULOS:
        app.include_router(modulo.router, prefix="/v1")

    # main.py es el unico lugar que conoce a todos los modulos: aqui se conectan.
    registrar_puerto_autorizacion(autorizacion.PuertoAutorizacionSQL())
    bus.limpiar()
    recepcion.registrar_suscripciones(bus)
    revision.registrar_suscripciones(bus)

    return app


app = crear_app()
