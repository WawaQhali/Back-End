"""Recepcion: recibe las imagenes donadas, ya cifradas, y las deja en cuarentena.

Interfaz publica: `router` y `registrar_suscripciones`. Otros modulos no lo importan
(seccion 3).
"""

from app.modules.recepcion.api import router
from app.modules.recepcion.servicio import al_revocar
from app.shared.eventos import AutorizacionRevocada, BusEventos


def registrar_suscripciones(bus: BusEventos) -> None:
    bus.suscribir(AutorizacionRevocada, "recepcion", al_revocar)


__all__ = ["registrar_suscripciones", "router"]
