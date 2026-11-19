"""Logica de negocio del modulo recepcion (seccion 6.3).

El backend NO descifra: valida el formato del paquete y lo guarda tal cual en la
cuarentena. Solo el servicio de reentrenamiento descifra, con Key Vault.
"""

import base64
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.recepcion import repositorio
from app.modules.recepcion.esquemas import ALGORITMO_PAQUETE, DonacionRecibida, PaqueteCifrado
from app.modules.recepcion.tablas import Paquete
from app.shared.errores import ErrorApi
from app.shared.eventos import AutorizacionRevocada
from app.shared.logs import hash_instalacion
from app.shared.proveedores import ProveedorBlob, ProveedorClaves, obtener_proveedor_blob
from app.shared.puertos import puerto_autorizacion

log = logging.getLogger(__name__)

CONTENEDOR = "cuarentena"
BYTES_CLAVE_CIFRADA = 384  # RSA 3072
BYTES_NONCE = 12
BYTES_MINIMOS_DATOS = 16  # al menos el tag de AES-GCM


def _formato(codigo: str, mensaje: str) -> ErrorApi:
    return ErrorApi(422, codigo, mensaje)


def _base64(valor: str) -> bytes:
    try:
        return base64.b64decode(valor, validate=True)
    except ValueError as error:  # binascii.Error hereda de ValueError
        raise _formato("base64_invalido", "Un campo del paquete no es base64 valido.") from error


async def validar_paquete(paquete: PaqueteCifrado, claves: ProveedorClaves) -> None:
    if paquete.v != 1:
        raise _formato("version_no_soportada", "Version de paquete no soportada.")
    if paquete.alg != ALGORITMO_PAQUETE:
        raise _formato("algoritmo_no_soportado", "Algoritmo de cifrado no soportado.")
    if paquete.kid not in await claves.kids_habilitados():
        raise _formato("kid_desconocido", "La clave usada no esta habilitada.")
    if len(_base64(paquete.clave_cifrada)) != BYTES_CLAVE_CIFRADA:
        raise _formato("tamano_invalido", "La clave cifrada no tiene 384 bytes.")
    if len(_base64(paquete.nonce)) != BYTES_NONCE:
        raise _formato("tamano_invalido", "El nonce no tiene 12 bytes.")
    if len(_base64(paquete.datos)) < BYTES_MINIMOS_DATOS:
        raise _formato("tamano_invalido", "Los datos cifrados son demasiado cortos.")


async def recibir(
    sesion: AsyncSession,
    installation_id: uuid.UUID,
    paquete: PaqueteCifrado,
    cuerpo: bytes,
    claves: ProveedorClaves,
    blob: ProveedorBlob,
) -> DonacionRecibida:
    if not await puerto_autorizacion().esta_vigente(sesion, installation_id):
        raise ErrorApi(403, "sin_autorizacion", "No hay una autorizacion vigente para donar.")
    await validar_paquete(paquete, claves)

    id_paquete = uuid.uuid4()
    blob_path = f"{CONTENEDOR}/{installation_id}/{id_paquete}.json"
    await blob.subir(blob_path, cuerpo, "application/json")  # el JSON tal cual llego
    try:
        sesion.add(
            Paquete(
                id=id_paquete,
                installation_id=installation_id,
                blob_path=blob_path,
                kid=paquete.kid,
            )
        )
        await sesion.commit()
    except Exception:
        await blob.borrar(blob_path)  # sin fila no debe quedar el blob
        raise
    return DonacionRecibida(id=id_paquete)


async def al_revocar(sesion: AsyncSession, evento: AutorizacionRevocada) -> None:
    """Borra los paquetes de la instalacion que siguen en cuarentena. Idempotente."""
    blob = obtener_proveedor_blob()
    paquetes = await repositorio.en_cuarentena_de(sesion, evento.installation_id)
    ahora = datetime.now(UTC)
    for paquete in paquetes:
        await blob.borrar(paquete.blob_path)
        paquete.eliminado_en = ahora
    log.info(
        "Revocacion: %d paquetes borrados de cuarentena (instalacion %s)",
        len(paquetes),
        hash_instalacion(evento.installation_id),
    )
