"""Endpoints del modulo autorizacion."""

import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Response, status

from app.modules.autorizacion import servicio
from app.modules.autorizacion.esquemas import EstadoAutorizacion, SolicitudAutorizacion
from app.shared.auth import id_instalacion
from app.shared.db import SesionBD, obtener_sesionador
from app.shared.errores import ErrorApi
from app.shared.eventos import bus

router = APIRouter(tags=["autorizacion"])

Instalacion = Annotated[uuid.UUID, Depends(id_instalacion)]

_OTRA_INSTALACION = {"description": "El X-Installation-Id no coincide con la instalacion pedida"}


def _misma_instalacion(cabecera: uuid.UUID, pedida: uuid.UUID) -> None:
    if cabecera != pedida:
        raise ErrorApi(403, "otra_instalacion", "Solo puedes gestionar tu propia instalacion.")


@router.post(
    "/autorizaciones",
    status_code=status.HTTP_201_CREATED,
    summary="Registrar el permiso de donar imagenes",
    responses={403: _OTRA_INSTALACION},
)
async def otorgar(
    solicitud: SolicitudAutorizacion, instalacion: Instalacion, sesion: SesionBD
) -> EstadoAutorizacion:
    _misma_instalacion(instalacion, solicitud.installation_id)
    return await servicio.otorgar(sesion, solicitud.installation_id, solicitud.version_texto)


@router.get(
    "/autorizaciones/{installation_id}",
    summary="Ver si la autorizacion esta vigente o revocada",
    responses={403: _OTRA_INSTALACION, 404: {"description": "Nunca se registro"}},
)
async def consultar(
    installation_id: uuid.UUID, instalacion: Instalacion, sesion: SesionBD
) -> EstadoAutorizacion:
    _misma_instalacion(instalacion, installation_id)
    return await servicio.consultar(sesion, installation_id)


@router.delete(
    "/autorizaciones/{installation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revocar la autorizacion y borrar las imagenes aun no usadas",
    responses={403: _OTRA_INSTALACION, 404: {"description": "Nunca se registro"}},
)
async def revocar(
    installation_id: uuid.UUID,
    instalacion: Instalacion,
    sesion: SesionBD,
    tareas: BackgroundTasks,
) -> Response:
    _misma_instalacion(instalacion, installation_id)
    if await servicio.revocar(sesion, installation_id, bus):
        # Recepcion y Revision borran sus imagenes al procesar el evento.
        tareas.add_task(bus.procesar_pendientes, obtener_sesionador())
    return Response(status_code=status.HTTP_204_NO_CONTENT)
