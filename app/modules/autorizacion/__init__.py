"""Autorizacion: registra y revoca el permiso de donar imagenes.

Interfaz publica: `router` y `PuertoAutorizacionSQL` (lo conecta main.py al puerto
de shared para que Recepcion consulte si hay autorizacion vigente).
Otros modulos no importan este paquete (seccion 3).
"""

from app.modules.autorizacion.api import router
from app.modules.autorizacion.servicio import PuertoAutorizacionSQL

__all__ = ["PuertoAutorizacionSQL", "router"]
