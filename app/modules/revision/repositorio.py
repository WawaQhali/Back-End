"""Consultas a la base de datos del modulo revision."""

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.revision.esquemas import EstadoImagen
from app.modules.revision.tablas import Imagen, Usuario


async def usuario_por_nombre(sesion: AsyncSession, usuario: str) -> Usuario | None:
    consulta = select(Usuario).where(Usuario.usuario == usuario)
    return (await sesion.execute(consulta)).scalar_one_or_none()


async def pendientes(
    sesion: AsyncSession, pagina: int, tamano: int
) -> tuple[Sequence[Imagen], int]:
    filtro = Imagen.estado == EstadoImagen.pendiente
    total = (await sesion.execute(select(func.count()).where(filtro))).scalar_one()
    consulta = (
        select(Imagen)
        .where(filtro)
        .order_by(Imagen.creado_en, Imagen.id)
        .offset((pagina - 1) * tamano)
        .limit(tamano)
    )
    return (await sesion.execute(consulta)).scalars().all(), total


async def imagen(
    sesion: AsyncSession, id_imagen: uuid.UUID, bloquear: bool = False
) -> Imagen | None:
    return await sesion.get(Imagen, id_imagen, with_for_update=bloquear)


async def etiquetadas_desde(sesion: AsyncSession, desde: datetime) -> Sequence[Imagen]:
    consulta = (
        select(Imagen)
        .where(Imagen.estado == EstadoImagen.revisada, Imagen.revisada_en >= desde)
        .order_by(Imagen.revisada_en)
    )
    return (await sesion.execute(consulta)).scalars().all()


async def no_usadas_de(sesion: AsyncSession, installation_id: uuid.UUID) -> Sequence[Imagen]:
    consulta = select(Imagen).where(
        Imagen.installation_id == installation_id, Imagen.usada_en_modelo.is_(None)
    )
    return (await sesion.execute(consulta)).scalars().all()


async def marcar_usadas(sesion: AsyncSession, ids: Sequence[uuid.UUID], version_modelo: str) -> int:
    resultado = await sesion.execute(
        update(Imagen)
        .where(Imagen.id.in_(ids), Imagen.estado == EstadoImagen.revisada)
        .values(usada_en_modelo=version_modelo)
    )
    return resultado.rowcount or 0
