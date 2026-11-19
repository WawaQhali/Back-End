"""Configuracion comun de pytest.

Las pruebas marcadas con `bd` usan PostgreSQL (`docker compose up -d`, base wawa_test).
Si no hay base, se saltan en local; en el CI (REQUIERE_BD=1) fallan.
"""

import asyncio
import os
import secrets
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest

# Valores de prueba antes de importar la app: nunca se usan fuera de pytest.
os.environ.setdefault("JWT_SECRET", secrets.token_urlsafe(48))
os.environ.setdefault("INTERNAL_API_KEY", secrets.token_urlsafe(48))
os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_PORT", "5432")
os.environ.setdefault("DB_NAME", "wawa_test")
os.environ.setdefault("DB_USER", "wawa")
os.environ.setdefault("DB_PASSWORD", "wawa_local")
# Siempre los proveedores falsos, aunque haya un .env con Azure o Azurite.
for _variable in (
    "KEYVAULT_URL",
    "AZURE_OPENAI_ENDPOINT",
    "STORAGE_ACCOUNT_URL",
    "STORAGE_CONNECTION_STRING",
):
    os.environ[_variable] = ""
os.environ.setdefault("CORS_ORIGINS", "http://localhost:5173")

import httpx  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.config import obtener_settings  # noqa: E402
from app.shared.db import crear_engine, obtener_sesionador  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]


async def _hay_bd() -> bool:
    engine = crear_engine(obtener_settings())
    try:
        async with engine.connect() as conexion:
            await conexion.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def _bd_migrada() -> Iterator[None]:
    """Deja la base de pruebas en `head`, empezando desde cero."""
    if not asyncio.run(_hay_bd()):
        mensaje = "PostgreSQL no disponible: corre `docker compose up -d`"
        if os.environ.get("REQUIERE_BD"):
            pytest.fail(mensaje)
        pytest.skip(mensaje)
    cfg = Config(str(RAIZ / "alembic.ini"))
    cfg.set_main_option("script_location", str(RAIZ / "migrations"))
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield


TABLAS = (
    "shared.eventos",
    "autorizacion.autorizaciones",
    "recepcion.paquetes",
    "revision.imagenes",
    "revision.usuarios",
    "modelos.versiones",
    "rag.fragmentos",
)


@pytest.fixture
async def sesionador(_bd_migrada: None):
    """Sesionador sobre la base de pruebas, con todas las tablas vacias en cada prueba."""
    fabrica = obtener_sesionador()
    async with fabrica() as sesion, sesion.begin():
        await sesion.execute(text(f"TRUNCATE {', '.join(TABLAS)}"))
    return fabrica


@pytest.fixture(autouse=True)
def _estado_limpio() -> None:
    """Limites de peticiones, Blob en memoria y LLM falso vuelven a cero."""
    from app.shared.limites import limitador
    from app.shared.proveedores import (
        ProveedorBlobMemoria,
        ProveedorLLMFalso,
        obtener_proveedor_blob,
        obtener_proveedor_llm,
    )

    limitador.reset()
    blob = obtener_proveedor_blob()
    llm = obtener_proveedor_llm()
    assert isinstance(blob, ProveedorBlobMemoria) and isinstance(llm, ProveedorLLMFalso)
    blob.blobs.clear()
    llm.respuesta = dict(ProveedorLLMFalso.RESPUESTA_POR_DEFECTO)
    llm.llamadas.clear()


@pytest.fixture
async def cliente() -> AsyncIterator[httpx.AsyncClient]:
    from app.main import app

    transporte = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transporte, base_url="http://prueba") as c:
        yield c


@pytest.fixture
async def cliente_bd(sesionador, cliente: httpx.AsyncClient) -> httpx.AsyncClient:  # noqa: ANN001
    """Cliente de la API con la base de pruebas limpia."""
    return cliente


@pytest.fixture
def blob():
    from app.shared.proveedores import obtener_proveedor_blob

    return obtener_proveedor_blob()


@pytest.fixture
def llm():
    from app.shared.proveedores import obtener_proveedor_llm

    return obtener_proveedor_llm()


@pytest.fixture
def claves():
    from app.shared.proveedores import obtener_proveedor_claves

    return obtener_proveedor_claves()
