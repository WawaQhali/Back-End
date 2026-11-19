"""Funciones compartidas por las pruebas."""

import base64
import json
import os
import uuid
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.shared.auth import Rol, emitir_token
from app.shared.proveedores import ProveedorClavesFalso

OAEP_SHA256 = padding.OAEP(
    mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None
)

# Respuestas completas del cuestionario v1, sin signos de alarma.
RESPUESTAS_V1: dict[str, bool | str] = {
    "dificultad_respirar": False,
    "labios_morados": False,
    "tos_repentina": False,
    "hinchazon_cara": False,
    "dificultad_tragar": False,
    "angustia": False,
    "vomitos_diarrea": False,
    "decaimiento": False,
    "picazon": True,
    "ronchas_cambian": True,
    "tiempo_evolucion": "menos_24h",
    "extension": "una_zona",
    "desencadenante": "infeccion",
    "muy_alergico": False,
}


def cabeceras_app(installation_id: object) -> dict[str, str]:
    return {"X-Installation-Id": str(installation_id)}


def cabeceras_rol(rol: Rol, usuario_id: str | None = None) -> dict[str, str]:
    return {"Authorization": f"Bearer {emitir_token(usuario_id or str(uuid.uuid4()), rol)}"}


def _b64(datos: bytes) -> str:
    return base64.b64encode(datos).decode()


def _entero(b64url: str) -> int:
    return int.from_bytes(base64.urlsafe_b64decode(b64url + "=" * (-len(b64url) % 4)), "big")


def armar_paquete(jwk: dict[str, str], installation_id: uuid.UUID, contenido: dict) -> dict:
    """Hace exactamente lo que hace la app (seccion 6.2)."""
    publica = rsa.RSAPublicNumbers(_entero(jwk["e"]), _entero(jwk["n"])).public_key()
    clave_aes = AESGCM.generate_key(bit_length=256)
    nonce = os.urandom(12)
    claro = json.dumps(contenido).encode()
    datos = AESGCM(clave_aes).encrypt(nonce, claro, str(installation_id).encode())
    return {
        "v": 1,
        "kid": jwk["kid"],
        "alg": "RSA-OAEP-256+A256GCM",
        "clave_cifrada": _b64(publica.encrypt(clave_aes, OAEP_SHA256)),
        "nonce": _b64(nonce),
        "datos": _b64(datos),
    }


def descifrar_paquete(
    paquete: dict[str, Any], installation_id: uuid.UUID, claves: ProveedorClavesFalso
) -> dict:
    """Lo que hace el servicio de reentrenamiento (seccion 6.4), con la clave local en
    lugar de Key Vault."""
    clave_aes = claves.desenvolver_para_pruebas(base64.b64decode(paquete["clave_cifrada"]))
    claro = AESGCM(clave_aes).decrypt(
        base64.b64decode(paquete["nonce"]),
        base64.b64decode(paquete["datos"]),
        str(installation_id).encode(),
    )
    return json.loads(claro)


def contenido_donado(jpeg: bytes = b"\xff\xd8\xff\xe0imagen-de-prueba\xff\xd9") -> dict:
    """El JSON en claro que arma la app: recorte JPEG en base64 + etiqueta preliminar."""
    return {
        "imagen_jpeg": _b64(jpeg),
        "etiqueta_preliminar": {
            "clase": "compatible",
            "confianza": 0.91,
            "respuestas": RESPUESTAS_V1,
            "version_modelo": "1.0.0",
            "version_cuestionario": "v1",
        },
    }
