"""Modelos de Pydantic de entrada y salida del modulo modelos."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Estado(StrEnum):
    candidato = "candidato"
    publicado = "publicado"
    bloqueado = "bloqueado"
    retirado = "retirado"


class Entrada(BaseModel):
    ancho: int = Field(gt=0, le=4096)
    alto: int = Field(gt=0, le=4096)
    canales: int = Field(ge=1, le=4)
    normalizacion: str = Field(min_length=1, max_length=200)


_EJEMPLO_ENTRADA = {"ancho": 224, "alto": 224, "canales": 3, "normalizacion": "0_255"}
_EJEMPLO_CLASES = ["compatible", "no_compatible", "indeterminado"]


class Candidato(BaseModel):
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    sensibilidad: float = Field(ge=0, le=1)
    blob_path: str = Field(pattern=r"^modelos/.+\.tflite$", max_length=300)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    tamano: int = Field(gt=0)
    entrada: Entrada
    clases: list[str] = Field(min_length=2, max_length=10)
    umbral_confianza: float = Field(ge=0, le=1)

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "version": "1.3.0",
                    "sensibilidad": 0.92,
                    "blob_path": "modelos/1.3.0/modelo.tflite",
                    "sha256": "a" * 64,
                    "tamano": 8421376,
                    "entrada": _EJEMPLO_ENTRADA,
                    "clases": _EJEMPLO_CLASES,
                    "umbral_confianza": 0.6,
                }
            ]
        }
    )

    @field_validator("clases")
    @classmethod
    def _sin_repetidas(cls, clases: list[str]) -> list[str]:
        if len(set(clases)) != len(clases):
            raise ValueError("Hay clases repetidas")
        return clases


class EstadoVersion(BaseModel):
    version: str
    estado: Estado
    sensibilidad: float
    publicado_en: datetime | None


class Manifiesto(BaseModel):
    version: str
    sha256: str
    tamano: int
    url: str  # SAS de 5 minutos
    entrada: Entrada
    clases: list[str]
    umbral_confianza: float

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "version": "1.3.0",
                    "sha256": "a" * 64,
                    "tamano": 8421376,
                    "url": "https://<cuenta>.blob.core.windows.net/modelos/1.3.0/modelo.tflite?<sas>",
                    "entrada": _EJEMPLO_ENTRADA,
                    "clases": _EJEMPLO_CLASES,
                    "umbral_confianza": 0.6,
                }
            ]
        }
    )
