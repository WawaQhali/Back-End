"""Endpoints del modulo recepcion."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status

from app.modules.recepcion import servicio
from app.modules.recepcion.esquemas import ClavePublica, DonacionRecibida, PaqueteCifrado
from app.shared.auth import id_instalacion
from app.shared.db import SesionBD
from app.shared.limites import LIMITE_DONACIONES, clave_instalacion_e_ip, limitador
from app.shared.proveedores import (
    ProveedorBlob,
    ProveedorClaves,
    obtener_proveedor_blob,
    obtener_proveedor_claves,
)

router = APIRouter(tags=["recepcion"])

Claves = Annotated[ProveedorClaves, Depends(obtener_proveedor_claves)]


@router.get(
    "/claves/publica",
    summary="Clave publica RSA (JWK) para cifrar la clave AES de cada donacion",
)
async def clave_publica(
    _instalacion: Annotated[uuid.UUID, Depends(id_instalacion)], claves: Claves
) -> ClavePublica:
    jwk = await claves.clave_publica()
    return ClavePublica(**jwk.model_dump())


@router.post(
    "/donaciones",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Recibir una imagen donada, ya cifrada, y dejarla en cuarentena",
    responses={
        403: {"description": "No hay autorizacion vigente para esta instalacion"},
        413: {"description": "El paquete pesa mas de 2 MB"},
        422: {"description": "Formato invalido: version, kid, base64 o tamanos"},
        429: {"description": "Mas de 10 donaciones por hora en esta instalacion"},
    },
)
@limitador.limit(LIMITE_DONACIONES, key_func=clave_instalacion_e_ip)
async def donar(
    request: Request,
    paquete: PaqueteCifrado,
    instalacion: Annotated[uuid.UUID, Depends(id_instalacion)],
    sesion: SesionBD,
    claves: Claves,
    blob: Annotated[ProveedorBlob, Depends(obtener_proveedor_blob)],
) -> DonacionRecibida:
    cuerpo = await request.body()
    return await servicio.recibir(sesion, instalacion, paquete, cuerpo, claves, blob)
