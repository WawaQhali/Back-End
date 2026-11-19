"""Consultas a la base de datos del modulo recepcion."""

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.recepcion.tablas import Paquete


async def en_cuarentena_de(sesion: AsyncSession, installation_id: uuid.UUID) -> Sequence[Paquete]:
    consulta = select(Paquete).where(
        Paquete.installation_id == installation_id, Paquete.eliminado_en.is_(None)
    )
    return (await sesion.execute(consulta)).scalars().all()
