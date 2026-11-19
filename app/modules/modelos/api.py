"""Endpoints del modulo modelos."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.modules.modelos import servicio
from app.modules.modelos.esquemas import Candidato, EstadoVersion, Manifiesto
from app.shared.auth import Rol, id_instalacion, requiere_rol, requiere_servicio_interno
from app.shared.db import SesionBD
from app.shared.proveedores import ProveedorBlob, obtener_proveedor_blob

router = APIRouter(tags=["modelos"])

_SOLO_EQUIPO = [Depends(requiere_rol(Rol.equipo))]


@router.get(
    "/modelos/manifiesto",
    summary="Modelo vigente: version, sha256, enlace temporal y contrato de entrada y salida",
    responses={404: {"description": "Todavia no hay un modelo publicado"}},
)
async def manifiesto(
    _instalacion: Annotated[uuid.UUID, Depends(id_instalacion)],
    sesion: SesionBD,
    blob: Annotated[ProveedorBlob, Depends(obtener_proveedor_blob)],
) -> Manifiesto:
    return await servicio.manifiesto(sesion, blob)


@router.post(
    "/interno/modelos/candidatos",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(requiere_servicio_interno)],
    summary="Registrar un modelo candidato (servicio de reentrenamiento)",
    responses={409: {"description": "Esa version ya existe"}},
)
async def registrar_candidato(candidato: Candidato, sesion: SesionBD) -> EstadoVersion:
    return await servicio.registrar_candidato(sesion, candidato)


@router.post(
    "/modelos/{version}/publicar",
    dependencies=_SOLO_EQUIPO,
    summary="Publicar un candidato si pasa la compuerta de sensibilidad",
    responses={
        404: {"description": "No existe esa version"},
        409: {
            "description": "Sensibilidad menor que la del vigente, cambio de clases o de "
            "tamano de entrada, o la version no es candidata. El vigente no cambia."
        },
    },
)
async def publicar(version: str, sesion: SesionBD) -> EstadoVersion:
    return await servicio.publicar(sesion, version)


@router.post(
    "/modelos/{version}/revertir",
    dependencies=_SOLO_EQUIPO,
    summary="Retirar la version vigente y volver a publicar la anterior",
    responses={
        404: {"description": "No existe esa version"},
        409: {"description": "No es la vigente o no hay version anterior"},
    },
)
async def revertir(version: str, sesion: SesionBD) -> EstadoVersion:
    return await servicio.revertir(sesion, version)
