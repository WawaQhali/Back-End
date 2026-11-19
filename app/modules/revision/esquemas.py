"""Modelos de Pydantic de entrada y salida del modulo revision."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr

from app.shared.auth import Rol


class EstadoImagen(StrEnum):
    pendiente = "pendiente"
    revisada = "revisada"
    eliminada = "eliminada"


class EtiquetaFinal(StrEnum):
    compatible = "compatible"
    no_compatible = "no_compatible"
    no_evaluable = "no_evaluable"


# --- Login ------------------------------------------------------------------------


class SolicitudLogin(BaseModel):
    usuario: str = Field(min_length=1, max_length=100)
    contrasena: str = Field(min_length=1, max_length=200)


class Token(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105  (no es una contrasena)
    expira_en: int = 3600
    rol: Rol


# --- Etiqueta preliminar (la arma la app; la registra el reentrenamiento) ----------


class EtiquetaPreliminar(BaseModel):
    """Clase y confianza del modelo, respuestas del cuestionario y version del modelo."""

    clase: Literal["compatible", "no_compatible", "indeterminado"]
    confianza: float = Field(ge=0, le=1)
    respuestas: dict[str, StrictBool | StrictStr]
    version_modelo: str = Field(max_length=50)
    version_cuestionario: str | None = Field(default=None, max_length=20)


class ImagenVerificada(BaseModel):
    paquete_id: uuid.UUID
    installation_id: uuid.UUID
    blob_path: str = Field(pattern=r"^verificadas/.+", max_length=300)
    etiqueta_preliminar: EtiquetaPreliminar

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "paquete_id": "6d0c3b6e-0d0f-4f57-9b5f-2a4f0b8c9e11",
                    "installation_id": "3f2c1d7e-8a4b-4c1e-9f0a-2b6d5e4c3a21",
                    "blob_path": "verificadas/6d0c3b6e-0d0f-4f57-9b5f-2a4f0b8c9e11.jpg",
                    "etiqueta_preliminar": {
                        "clase": "compatible",
                        "confianza": 0.91,
                        "respuestas": {"picazon": True, "tiempo_evolucion": "menos_24h"},
                        "version_modelo": "1.3.0",
                        "version_cuestionario": "v1",
                    },
                }
            ]
        }
    )


class Registrada(BaseModel):
    id: uuid.UUID


# --- App web del medico -----------------------------------------------------------------


class ResumenImagen(BaseModel):
    id: uuid.UUID
    recibida_en: datetime
    clase: str
    confianza: float


class PaginaPendientes(BaseModel):
    items: list[ResumenImagen]
    total: int
    pagina: int
    tamano: int


class DetalleImagen(BaseModel):
    id: uuid.UUID
    estado: EstadoImagen
    recibida_en: datetime
    etiqueta_preliminar: EtiquetaPreliminar
    etiqueta_final: EtiquetaFinal | None
    comentario: str | None
    url: str  # SAS de 5 minutos


class SolicitudEtiqueta(BaseModel):
    etiqueta: EtiquetaFinal
    comentario: str | None = Field(default=None, max_length=500)

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"etiqueta": "compatible", "comentario": None}]}
    )


# --- Servicio de reentrenamiento ------------------------------------------------------


class EtiquetaParaEntrenar(BaseModel):
    id: uuid.UUID
    paquete_id: uuid.UUID
    blob_path: str
    etiqueta_final: EtiquetaFinal
    etiqueta_preliminar: EtiquetaPreliminar
    revisada_en: datetime


class MarcarUsadas(BaseModel):
    version_modelo: str = Field(max_length=50)
    ids: list[uuid.UUID] = Field(min_length=1, max_length=5000)


class Marcadas(BaseModel):
    marcadas: int
