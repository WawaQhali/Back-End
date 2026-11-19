"""Consultas a la base de datos del modulo orientacion."""

from collections.abc import Sequence

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.orientacion.tablas import Fragmento


async def mas_cercanos(
    sesion: AsyncSession, vector: list[float], cantidad: int
) -> list[tuple[Fragmento, float]]:
    """Los `cantidad` fragmentos mas cercanos por distancia coseno (operador <=>)."""
    distancia = Fragmento.embedding.cosine_distance(vector).label("distancia")
    filas = await sesion.execute(select(Fragmento, distancia).order_by(distancia).limit(cantidad))
    return [(fragmento, float(d)) for fragmento, d in filas.all()]


async def reemplazar_documento(
    sesion: AsyncSession, documento: str, fragmentos: Sequence[Fragmento]
) -> None:
    """Borra los fragmentos anteriores del documento y guarda los nuevos."""
    await sesion.execute(delete(Fragmento).where(Fragmento.documento == documento))
    sesion.add_all(fragmentos)
    await sesion.flush()
