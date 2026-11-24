"""Endpoints del modulo revision."""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status

from app.modules.revision import servicio
from app.modules.revision.esquemas import (
    DetalleImagen,
    EtiquetaParaEntrenar,
    ImagenVerificada,
    Marcadas,
    MarcarUsadas,
    PaginaPendientes,
    Registrada,
    SolicitudEtiqueta,
    SolicitudLogin,
    Token,
)
from app.shared.auth import Rol, Sesion, requiere_rol, requiere_servicio_interno
from app.shared.db import SesionBD
from app.shared.limites import LIMITE_LOGIN, limitador
from app.shared.proveedores import ProveedorBlob, obtener_proveedor_blob

router = APIRouter(tags=["revision"])

Medico = Annotated[Sesion, Depends(requiere_rol(Rol.medico))]
Blob = Annotated[ProveedorBlob, Depends(obtener_proveedor_blob)]
_INTERNO = [Depends(requiere_servicio_interno)]
_NO_EXISTE = {404: {"description": "No existe la imagen o fue eliminada"}}


@router.post(
    "/auth/login",
    summary="Login del medico: JWT de 1 hora",
    responses={
        401: {"description": "Usuario o contrasena incorrectos"},
        429: {"description": "Mas de 5 intentos por minuto desde esta IP"},
    },
)
@limitador.limit(LIMITE_LOGIN)
async def login(request: Request, datos: SolicitudLogin, sesion: SesionBD) -> Token:
    return await servicio.login(sesion, datos.usuario, datos.contrasena)


@router.get(
    "/revision/pendientes",
    summary="Imagenes verificadas sin etiqueta final, de la mas antigua a la mas nueva",
)
async def pendientes(
    _medico: Medico,
    sesion: SesionBD,
    pagina: Annotated[int, Query(ge=1)] = 1,
    tamano: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PaginaPendientes:
    return await servicio.pendientes(sesion, pagina, tamano)


@router.get(
    "/revision/{id_imagen}",
    summary="Etiqueta preliminar y enlace de lectura que vence en 5 minutos",
    responses=_NO_EXISTE,
)
async def detalle(
    id_imagen: uuid.UUID, _medico: Medico, sesion: SesionBD, blob: Blob
) -> DetalleImagen:
    return await servicio.detalle(sesion, id_imagen, blob)


@router.post(
    "/revision/{id_imagen}/etiqueta",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Guardar la etiqueta final: compatible, no_compatible o no_evaluable",
    responses={**_NO_EXISTE, 409: {"description": "Ya se uso en un modelo"}},
)
async def etiquetar(
    id_imagen: uuid.UUID, solicitud: SolicitudEtiqueta, medico: Medico, sesion: SesionBD
) -> Response:
    await servicio.etiquetar(sesion, id_imagen, solicitud, medico)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/revision/{id_imagen}/eliminar",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar una imagen con datos identificables (p. ej. un rostro)",
    responses=_NO_EXISTE,
)
async def eliminar(id_imagen: uuid.UUID, _medico: Medico, sesion: SesionBD, blob: Blob) -> Response:
    await servicio.eliminar(sesion, id_imagen, blob)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/interno/revision/verificadas",
    status_code=status.HTTP_201_CREATED,
    dependencies=_INTERNO,
    summary="Registrar una imagen ya descifrada, sin rostro, con su etiqueta preliminar",
    responses={409: {"description": "Ese paquete ya fue registrado"}},
)
async def registrar_verificada(datos: ImagenVerificada, sesion: SesionBD) -> Registrada:
    return await servicio.registrar_verificada(sesion, datos)


@router.get(
    "/interno/revision/etiquetas",
    dependencies=_INTERNO,
    summary="Etiquetas finales desde una fecha (ISO 8601)",
)
async def etiquetas(
    desde: Annotated[datetime, Query(examples=["2026-11-20T00:00:00Z"])], sesion: SesionBD
) -> list[EtiquetaParaEntrenar]:
    return await servicio.etiquetas_desde(sesion, desde)


@router.post(
    "/interno/revision/usadas",
    dependencies=_INTERNO,
    summary="Marcar imagenes como usadas en un modelo (se conservan al revocar)",
)
async def marcar_usadas(datos: MarcarUsadas, sesion: SesionBD) -> Marcadas:
    return Marcadas(marcadas=await servicio.marcar_usadas(sesion, datos.ids, datos.version_modelo))
