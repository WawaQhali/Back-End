"""Consultas sincronas entre modulos sin que se importen entre si (seccion 3).

`shared` define la interfaz, el modulo dueno la implementa y `main.py` las conecta.
Asi Recepcion puede preguntar si hay autorizacion vigente sin importar Autorizacion.
Ver docs/decisiones.md (D11).
"""

import uuid
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession


class PuertoAutorizacion(Protocol):
    async def esta_vigente(self, sesion: AsyncSession, installation_id: uuid.UUID) -> bool: ...


_autorizacion: PuertoAutorizacion | None = None


def registrar_puerto_autorizacion(implementacion: PuertoAutorizacion) -> None:
    global _autorizacion
    _autorizacion = implementacion


def puerto_autorizacion() -> PuertoAutorizacion:
    if _autorizacion is None:
        raise RuntimeError("Falta registrar el puerto de autorizacion en main.py")
    return _autorizacion
