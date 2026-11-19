"""Modelos de Pydantic de entrada y salida del modulo recepcion (seccion 6.2)."""

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ALGORITMO_PAQUETE = "RSA-OAEP-256+A256GCM"


class PaqueteCifrado(BaseModel):
    """Formato fijo del paquete que arma la app. El backend no lo descifra."""

    v: int
    kid: str = Field(max_length=500)
    alg: str = Field(max_length=50)
    clave_cifrada: str = Field(max_length=1000)  # base64, 384 bytes
    nonce: str = Field(max_length=100)  # base64, 12 bytes
    datos: str  # base64, texto cifrado + tag de 16 bytes (el limite lo pone el de 2 MB)

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "v": 1,
                    "kid": "https://wawa-kv.vault.azure.net/keys/wawa-donaciones/0123abcd",
                    "alg": ALGORITMO_PAQUETE,
                    "clave_cifrada": "<base64 de 384 bytes>",
                    "nonce": "<base64 de 12 bytes>",
                    "datos": "<base64: texto cifrado + tag de 16 bytes>",
                }
            ]
        },
    )


class DonacionRecibida(BaseModel):
    id: uuid.UUID
    estado: Literal["en_cuarentena"] = "en_cuarentena"


class ClavePublica(BaseModel):
    kty: str
    n: str
    e: str
    kid: str
    alg: str
