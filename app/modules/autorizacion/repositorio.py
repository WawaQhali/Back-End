"""Consultas a la base de datos del modulo autorizacion."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.autorizacion.tablas import Autorizacion


async def obtener(
    sesion: AsyncSession, installation_id: uuid.UUID, bloquear: bool = False
) -> Autorizacion | None:
    return await sesion.get(Autorizacion, installation_id, with_for_update=bloquear)
