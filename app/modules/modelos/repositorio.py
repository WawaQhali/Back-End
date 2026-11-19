"""Consultas a la base de datos del modulo modelos."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.modelos.esquemas import Estado
from app.modules.modelos.tablas import VersionModelo


async def obtener(
    sesion: AsyncSession, version: str, bloquear: bool = False
) -> VersionModelo | None:
    return await sesion.get(VersionModelo, version, with_for_update=bloquear)


async def vigente(sesion: AsyncSession, bloquear: bool = False) -> VersionModelo | None:
    consulta = select(VersionModelo).where(VersionModelo.estado == Estado.publicado)
    if bloquear:
        consulta = consulta.with_for_update()
    return (await sesion.execute(consulta)).scalar_one_or_none()


async def anterior_retirada(sesion: AsyncSession, excluir: str) -> VersionModelo | None:
    """La ultima version publicada antes que la vigente (estado retirado)."""
    consulta = (
        select(VersionModelo)
        .where(
            VersionModelo.estado == Estado.retirado,
            VersionModelo.publicado_en.is_not(None),
            VersionModelo.version != excluir,
        )
        .order_by(VersionModelo.publicado_en.desc())
        .limit(1)
        .with_for_update()
    )
    return (await sesion.execute(consulta)).scalar_one_or_none()
