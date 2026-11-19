"""Revision: muestra al medico las imagenes verificadas y guarda su etiqueta.

Interfaz publica: `router` y `registrar_suscripciones`. Otros modulos no lo importan
(seccion 3).
"""

from app.modules.revision.api import router
from app.modules.revision.servicio import al_revocar, asegurar_cuenta_fija
from app.shared.eventos import AutorizacionRevocada, BusEventos


def registrar_suscripciones(bus: BusEventos) -> None:
    bus.suscribir(AutorizacionRevocada, "revision", al_revocar)


__all__ = ["asegurar_cuenta_fija", "registrar_suscripciones", "router"]
