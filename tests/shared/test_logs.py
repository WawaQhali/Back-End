"""El installation_id nunca aparece en claro en los logs (seccion 9)."""

import logging
import uuid

from app.shared.logs import FiltroUUID, hash_instalacion


def test_uuid_en_la_ruta_del_access_log_se_registra_como_hash() -> None:
    instalacion = uuid.uuid4()
    registro = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("1.2.3.4", "DELETE", f"/v1/autorizaciones/{instalacion}", "1.1", 204),
        None,
    )
    FiltroUUID().filter(registro)
    linea = registro.getMessage()
    assert str(instalacion) not in linea
    assert hash_instalacion(instalacion) in linea


def test_hash_no_depende_de_mayusculas() -> None:
    instalacion = uuid.uuid4()
    assert hash_instalacion(str(instalacion).upper()) == hash_instalacion(instalacion)
