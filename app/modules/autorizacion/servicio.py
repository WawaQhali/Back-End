"""Logica de negocio del modulo autorizacion."""

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.autorizacion import repositorio
from app.modules.autorizacion.esquemas import EstadoAutorizacion
from app.modules.autorizacion.tablas import Autorizacion
from app.shared.errores import ErrorApi
from app.shared.eventos import AutorizacionRevocada, BusEventos


def _estado(fila: Autorizacion) -> EstadoAutorizacion:
    return EstadoAutorizacion(
        installation_id=fila.installation_id,
        estado="vigente" if fila.vigente else "revocada",
        version_texto=fila.version_texto,
        otorgada_en=fila.otorgada_en,
        revocada_en=fila.revocada_en,
    )


async def otorgar(
    sesion: AsyncSession, installation_id: uuid.UUID, version_texto: str
) -> EstadoAutorizacion:
    """Registra la autorizacion. Si ya existia (vigente o revocada), la renueva."""
    ahora = datetime.now(UTC)
    fila = await repositorio.obtener(sesion, installation_id, bloquear=True)
    if fila is None:
        fila = Autorizacion(installation_id=installation_id)
        sesion.add(fila)
    fila.version_texto = version_texto
    fila.otorgada_en = ahora
    fila.revocada_en = None
    await sesion.commit()
    return _estado(fila)


async def consultar(sesion: AsyncSession, installation_id: uuid.UUID) -> EstadoAutorizacion:
    fila = await repositorio.obtener(sesion, installation_id)
    if fila is None:
        raise ErrorApi(404, "sin_autorizacion", "No hay autorizacion registrada.")
    return _estado(fila)


async def revocar(sesion: AsyncSession, installation_id: uuid.UUID, bus: BusEventos) -> bool:
    """Revoca y publica AutorizacionRevocada en la MISMA transaccion (seccion 3).
    Devuelve True si hubo un cambio (ya revocada = no se publica otra vez)."""
    fila = await repositorio.obtener(sesion, installation_id, bloquear=True)
    if fila is None:
        raise ErrorApi(404, "sin_autorizacion", "No hay autorizacion registrada.")
    if not fila.vigente:
        return False
    fila.revocada_en = datetime.now(UTC)
    await bus.publicar(sesion, AutorizacionRevocada(installation_id))
    await sesion.commit()
    return True


class PuertoAutorizacionSQL:
    """Implementa shared.puertos.PuertoAutorizacion para Recepcion."""

    async def esta_vigente(self, sesion: AsyncSession, installation_id: uuid.UUID) -> bool:
        fila = await repositorio.obtener(sesion, installation_id)
        return fila is not None and fila.vigente
