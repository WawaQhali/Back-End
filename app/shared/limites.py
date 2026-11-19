"""Limite de peticiones (slowapi) y de tamano del cuerpo (seccion 9)."""

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.shared.errores import respuesta_error

TAMANO_MAXIMO_BYTES = 2 * 1024 * 1024  # 2 MB

# Limites de la seccion 9; los usan los routers con @limitador.limit(...)
LIMITE_ORIENTACION = "20/hour"
LIMITE_DONACIONES = "10/hour"
LIMITE_LOGIN = "5/minute"


def clave_instalacion_e_ip(request: Request) -> str:
    """Por instalacion e IP, para los endpoints de la app movil."""
    instalacion = request.headers.get("x-installation-id", "-")
    return f"{instalacion}|{get_remote_address(request)}"


limitador = Limiter(key_func=get_remote_address)


class LimiteTamanoPeticion:
    """Responde 413 si el cuerpo supera el maximo, por Content-Length o por lo leido."""

    def __init__(self, app: ASGIApp, maximo: int = TAMANO_MAXIMO_BYTES) -> None:
        self.app = app
        self.maximo = maximo

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        for nombre, valor in scope.get("headers", []):
            if nombre == b"content-length":
                try:
                    excede = int(valor) > self.maximo
                except ValueError:
                    excede = False
                if excede:
                    respuesta = respuesta_error(
                        413, "peticion_muy_grande", "La peticion supera los 2 MB."
                    )
                    await respuesta(scope, receive, send)
                    return

        # Sin Content-Length (cuerpo en trozos): se cuenta lo leido. Al pasarse, la app
        # recibe una desconexion, su respuesta se descarta y se responde 413 desde aqui.
        leidos = 0
        excedido = False
        respuesta_iniciada = False

        async def _receive_limitado() -> Message:
            nonlocal leidos, excedido
            if excedido:
                return {"type": "http.disconnect"}
            mensaje = await receive()
            if mensaje["type"] == "http.request":
                leidos += len(mensaje.get("body", b""))
                if leidos > self.maximo:
                    excedido = True
                    return {"type": "http.disconnect"}
            return mensaje

        async def _send_controlado(mensaje: Message) -> None:
            nonlocal respuesta_iniciada
            if excedido and not respuesta_iniciada:
                return
            respuesta_iniciada = True
            await send(mensaje)

        await self.app(scope, _receive_limitado, _send_controlado)

        if excedido and not respuesta_iniciada:
            respuesta = respuesta_error(413, "peticion_muy_grande", "La peticion supera los 2 MB.")
            await respuesta(scope, receive, send)
