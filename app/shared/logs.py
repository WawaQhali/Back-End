"""Logs sin datos personales (seccion 9): nunca cuerpos, sintomas ni texto libre, y el
installation_id solo como hash, tambien cuando aparece en la ruta de una peticion."""

import hashlib
import logging
import re

_PATRON_UUID = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


def hash_instalacion(installation_id: object) -> str:
    return hashlib.sha256(str(installation_id).lower().encode()).hexdigest()[:16]


def _ocultar_uuids(texto: str) -> str:
    return _PATRON_UUID.sub(lambda m: f"inst:{hash_instalacion(m.group(0))}", texto)


class FiltroUUID(logging.Filter):
    """Reemplaza cualquier UUID de los argumentos del log por su hash."""

    def filter(self, registro: logging.LogRecord) -> bool:
        if isinstance(registro.args, tuple):
            registro.args = tuple(
                _ocultar_uuids(a) if isinstance(a, str) else a for a in registro.args
            )
        if isinstance(registro.msg, str):
            registro.msg = _ocultar_uuids(registro.msg)
        return True


def configurar_logs(nivel: str) -> None:
    logging.basicConfig(
        level=nivel.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    filtro = FiltroUUID()
    for nombre in ("", "uvicorn", "uvicorn.access", "uvicorn.error", "app"):
        registrador = logging.getLogger(nombre)
        if not any(isinstance(f, FiltroUUID) for f in registrador.filters):
            registrador.addFilter(filtro)
