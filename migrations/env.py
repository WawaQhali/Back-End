"""Entorno de Alembic. Se ejecuta como paso del despliegue: `alembic upgrade head`."""

import asyncio
import importlib
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection

import app.shared.eventos  # noqa: F401  (registra shared.eventos en el metadata)
from app.config import obtener_settings
from app.shared.db import Base, crear_engine

# Registra las tablas de cada modulo para que autogenerate las vea.
for _modulo in ("autorizacion", "recepcion", "revision", "orientacion", "modelos"):
    importlib.import_module(f"app.modules.{_modulo}.tablas")

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _configurar(conexion: Connection) -> None:
    context.configure(
        connection=conexion,
        target_metadata=target_metadata,
        include_schemas=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def _migrar_en_linea() -> None:
    engine = crear_engine(obtener_settings())
    async with engine.connect() as conexion:
        await conexion.run_sync(_configurar)
    await engine.dispose()


if context.is_offline_mode():
    raise SystemExit("Solo se soporta el modo en linea: alembic upgrade head")

asyncio.run(_migrar_en_linea())
