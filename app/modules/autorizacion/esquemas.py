"""Modelos de Pydantic de entrada y salida del modulo autorizacion."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SolicitudAutorizacion(BaseModel):
    installation_id: uuid.UUID
    # Version del texto de autorizacion que el padre leyo y acepto.
    version_texto: str = Field(min_length=1, max_length=20)

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"installation_id": "3f2c1d7e-8a4b-4c1e-9f0a-2b6d5e4c3a21", "version_texto": "v1"}
            ]
        }
    )


class EstadoAutorizacion(BaseModel):
    installation_id: uuid.UUID
    estado: Literal["vigente", "revocada"]
    version_texto: str
    otorgada_en: datetime
    revocada_en: datetime | None

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "installation_id": "3f2c1d7e-8a4b-4c1e-9f0a-2b6d5e4c3a21",
                    "estado": "vigente",
                    "version_texto": "v1",
                    "otorgada_en": "2026-11-21T15:04:05Z",
                    "revocada_en": None,
                }
            ]
        }
    )
