"""Engine y sesion async de SQLAlchemy sobre PostgreSQL (asyncpg)."""

from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy import MetaData, event
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import Settings, obtener_settings

# Esquemas de PostgreSQL: uno por modulo, mas shared y rag (seccion 3 y 8).
ESQUEMAS = ("shared", "autorizacion", "recepcion", "revision", "modelos", "rag")

_CONVENCION_NOMBRES = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# Alcance del token de Entra ID para Azure Database for PostgreSQL.
_ALCANCE_POSTGRES_AAD = "https://ossrdbms-aad.database.windows.net/.default"


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=_CONVENCION_NOMBRES)


def url_bd(settings: Settings) -> URL:
    return URL.create(
        "postgresql+asyncpg",
        username=settings.db_user,
        password=settings.db_password.get_secret_value() if settings.db_password else None,
        host=settings.db_host,
        port=settings.db_port,
        database=settings.db_name,
    )


def crear_engine(settings: Settings) -> AsyncEngine:
    connect_args: dict[str, object] = {"timeout": 5}
    if settings.usa_identidad_gestionada_bd:
        connect_args["ssl"] = "require"

    engine = create_async_engine(url_bd(settings), pool_pre_ping=True, connect_args=connect_args)

    if settings.usa_identidad_gestionada_bd:
        from azure.identity import DefaultAzureCredential

        credencial = DefaultAzureCredential()

        @event.listens_for(engine.sync_engine, "do_connect")
        def _usar_token(dialect, conn_rec, cargs, cparams) -> None:  # noqa: ANN001
            # El token dura ~1 h; la credencial lo cachea y lo renueva sola.
            cparams["password"] = credencial.get_token(_ALCANCE_POSTGRES_AAD).token

    return engine


@lru_cache
def obtener_engine() -> AsyncEngine:
    return crear_engine(obtener_settings())


@lru_cache
def obtener_sesionador() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(obtener_engine(), expire_on_commit=False)


async def sesion_bd() -> AsyncIterator[AsyncSession]:
    """Dependencia de FastAPI: una sesion por peticion."""
    async with obtener_sesionador()() as sesion:
        yield sesion


SesionBD = Annotated[AsyncSession, Depends(sesion_bd)]
