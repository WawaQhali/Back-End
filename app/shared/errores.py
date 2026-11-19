"""Errores de la API: el cliente recibe un codigo y un mensaje generico; el detalle
queda solo en los logs (seccion 9). Nunca se devuelve ni se registra el cuerpo."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger(__name__)

_CODIGOS_HTTP = {
    400: ("peticion_invalida", "La peticion no es valida."),
    401: ("no_autenticado", "No autenticado."),
    403: ("sin_permiso", "No tienes permiso para esta accion."),
    404: ("no_encontrado", "No encontrado."),
    405: ("metodo_no_permitido", "Metodo no permitido."),
    409: ("conflicto", "La operacion entra en conflicto con el estado actual."),
    413: ("peticion_muy_grande", "La peticion supera el tamano permitido."),
    422: ("entrada_invalida", "La peticion no tiene el formato esperado."),
    429: ("demasiadas_peticiones", "Demasiadas peticiones. Intenta mas tarde."),
    503: ("no_disponible", "Servicio no disponible por ahora."),
}


class ErrorApi(Exception):
    """Error esperado que se devuelve al cliente tal cual (codigo + mensaje)."""

    def __init__(self, status: int, codigo: str, mensaje: str) -> None:
        super().__init__(f"{status} {codigo}")
        self.status = status
        self.codigo = codigo
        self.mensaje = mensaje


def respuesta_error(status: int, codigo: str, mensaje: str, **extra: object) -> JSONResponse:
    return JSONResponse(
        status_code=status, content={"error": {"codigo": codigo, "mensaje": mensaje, **extra}}
    )


def _generico(status: int) -> JSONResponse:
    codigo, mensaje = _CODIGOS_HTTP.get(status, ("error", "Ocurrio un error."))
    return respuesta_error(status, codigo, mensaje)


def registrar_manejadores(app: FastAPI) -> None:
    @app.exception_handler(ErrorApi)
    async def _error_api(_: Request, error: ErrorApi) -> JSONResponse:
        return respuesta_error(error.status, error.codigo, error.mensaje)

    @app.exception_handler(RequestValidationError)
    async def _validacion(_: Request, error: RequestValidationError) -> JSONResponse:
        # Solo la ubicacion de los campos: nunca los valores recibidos.
        campos = sorted({".".join(str(p) for p in e.get("loc", ())) for e in error.errors()})
        codigo, mensaje = _CODIGOS_HTTP[422]
        return respuesta_error(422, codigo, mensaje, campos=campos)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, error: StarletteHTTPException) -> JSONResponse:
        return _generico(error.status_code)

    @app.exception_handler(RateLimitExceeded)
    async def _limite(_: Request, __: RateLimitExceeded) -> JSONResponse:
        return _generico(429)

    @app.exception_handler(Exception)
    async def _inesperado(request: Request, error: Exception) -> JSONResponse:
        log.error(
            "Error no controlado en %s %s: %s",
            request.method,
            request.url.path,
            type(error).__name__,
            exc_info=error,
        )
        return respuesta_error(500, "error_interno", "Ocurrio un error. Intenta mas tarde.")
