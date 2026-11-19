"""Endpoints del modulo orientacion."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.modules.orientacion import servicio
from app.modules.orientacion.esquemas import ConsultaOrientacion, RespuestaOrientacion
from app.shared.auth import id_instalacion
from app.shared.db import SesionBD
from app.shared.limites import LIMITE_ORIENTACION, clave_instalacion_e_ip, limitador
from app.shared.proveedores import ProveedorLLM, obtener_proveedor_llm

router = APIRouter(tags=["orientacion"])

_ERROR = {"error": {"codigo": "...", "mensaje": "..."}}


@router.post(
    "/orientacion",
    summary="Recomendaciones con RAG para la severidad que calculo la app",
    response_model=RespuestaOrientacion,
    responses={
        422: {
            "description": "Version del cuestionario distinta, pregunta u opcion inexistente, "
            "o signo de alarma con severidad distinta de alta",
            "content": {"application/json": {"example": _ERROR}},
        },
        429: {"description": "Mas de 20 consultas por hora en esta instalacion"},
        503: {
            "description": "El LLM fallo o su respuesta no paso la validacion: la app usa "
            "sus recomendaciones locales",
            "content": {
                "application/json": {
                    "example": {
                        "error": {
                            "codigo": "orientacion_no_disponible",
                            "mensaje": "No se pudo generar la orientacion. Usa el respaldo local.",
                        }
                    }
                }
            },
        },
    },
)
@limitador.limit(LIMITE_ORIENTACION, key_func=clave_instalacion_e_ip)
async def orientacion(
    request: Request,
    consulta: ConsultaOrientacion,
    _instalacion: Annotated[uuid.UUID, Depends(id_instalacion)],
    sesion: SesionBD,
    llm: Annotated[ProveedorLLM, Depends(obtener_proveedor_llm)],
) -> RespuestaOrientacion:
    return await servicio.orientar(consulta, sesion, llm)
