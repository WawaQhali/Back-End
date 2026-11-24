"""Identificacion de quien llama (seccion 4).

- App movil: header X-Installation-Id (UUID aleatorio de la instalacion).
- Medico: JWT Bearer HS256 de 1 hora con rol `medico` (es el unico rol con login, D39).
- Servicio de reentrenamiento: header X-Api-Key, solo en /v1/interno/*.
"""

import hmac
import uuid
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Annotated

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, Header
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from app.config import obtener_settings
from app.shared.errores import ErrorApi

ALGORITMO_JWT = "HS256"
DURACION_TOKEN = timedelta(hours=1)

_hasher = PasswordHasher()
_bearer = HTTPBearer(auto_error=False)


class Rol(StrEnum):
    """Solo el medico entra con usuario y contrasena (D39: se quito el rol `equipo`)."""

    medico = "medico"


class Sesion(BaseModel):
    usuario_id: str
    rol: Rol


# --- Contrasenas -------------------------------------------------------------


def hashear_contrasena(contrasena: str) -> str:
    return _hasher.hash(contrasena)


def verificar_contrasena(hash_guardado: str, contrasena: str) -> bool:
    try:
        return _hasher.verify(hash_guardado, contrasena)
    except (VerificationError, InvalidHashError):
        return False


# --- JWT -------------------------------------------------------------------------


def emitir_token(usuario_id: str, rol: Rol, ahora: datetime | None = None) -> str:
    ahora = ahora or datetime.now(UTC)
    datos = {"sub": usuario_id, "rol": rol.value, "iat": ahora, "exp": ahora + DURACION_TOKEN}
    secreto = obtener_settings().jwt_secret.get_secret_value()
    return jwt.encode(datos, secreto, algorithm=ALGORITMO_JWT)


def leer_token(token: str) -> Sesion:
    secreto = obtener_settings().jwt_secret.get_secret_value()
    try:
        datos = jwt.decode(
            token, secreto, algorithms=[ALGORITMO_JWT], options={"require": ["exp", "sub"]}
        )
        return Sesion(usuario_id=datos["sub"], rol=Rol(datos["rol"]))
    except (jwt.PyJWTError, KeyError, ValueError) as error:
        raise ErrorApi(401, "no_autenticado", "Sesion no valida o vencida.") from error


def requiere_rol(*roles: Rol):
    """Dependencia: exige un JWT valido con alguno de los roles indicados."""

    async def _dependencia(
        credenciales: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    ) -> Sesion:
        if credenciales is None:
            raise ErrorApi(401, "no_autenticado", "Falta el token de acceso.")
        sesion = leer_token(credenciales.credentials)
        if sesion.rol not in roles:
            raise ErrorApi(403, "sin_permiso", "No tienes permiso para esta accion.")
        return sesion

    return _dependencia


# --- Servicio interno ---------------------------------------------------------------


async def requiere_servicio_interno(
    x_api_key: Annotated[str | None, Header(alias="X-Api-Key")] = None,
) -> None:
    esperada = obtener_settings().internal_api_key.get_secret_value()
    if x_api_key is None or not hmac.compare_digest(x_api_key.encode(), esperada.encode()):
        raise ErrorApi(401, "no_autenticado", "Clave de servicio no valida.")


# --- App movil ------------------------------------------------------------------


async def id_instalacion(
    x_installation_id: Annotated[uuid.UUID, Header(alias="X-Installation-Id")],
) -> uuid.UUID:
    return x_installation_id
