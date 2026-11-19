"""Proveedores falsos: misma interfaz que Azure, sin salir a la red."""

import base64
import math
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.config import Settings
from app.shared.proveedores import (
    DIMENSION_EMBEDDING,
    ProveedorClavesFalso,
    ProveedorLLMFalso,
    crear_proveedor_claves,
    crear_proveedor_llm,
)


def _desde_b64url(texto: str) -> int:
    relleno = "=" * (-len(texto) % 4)
    return int.from_bytes(base64.urlsafe_b64decode(texto + relleno), "big")


async def test_clave_publica_falsa_es_un_jwk_rsa_3072() -> None:
    proveedor = ProveedorClavesFalso()
    jwk = await proveedor.clave_publica()
    assert jwk.kty == "RSA"
    assert jwk.alg == "RSA-OAEP-256"
    assert jwk.kid in await proveedor.kids_habilitados()
    assert _desde_b64url(jwk.n).bit_length() == 3072


async def test_envoltura_rsa_oaep_256_ida_y_vuelta() -> None:
    """Lo que haria la app con el JWK: SHA-256 en el hash y en MGF1 (seccion 6.2)."""
    proveedor = ProveedorClavesFalso()
    jwk = await proveedor.clave_publica()
    publica = rsa.RSAPublicNumbers(_desde_b64url(jwk.e), _desde_b64url(jwk.n)).public_key()
    clave_aes = os.urandom(32)
    envuelta = publica.encrypt(
        clave_aes,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None
        ),
    )
    assert len(envuelta) == 384
    assert proveedor.desenvolver_para_pruebas(envuelta) == clave_aes


async def test_embeddings_falsos_son_deterministas_y_normalizados() -> None:
    llm = ProveedorLLMFalso()
    a1, a2, b = await llm.embeddings(["ronchas", "ronchas", "otra cosa"])
    assert len(a1) == DIMENSION_EMBEDDING
    assert a1 == a2
    assert a1 != b
    assert math.isclose(sum(v * v for v in a1), 1.0, rel_tol=1e-9)


async def test_llm_falso_devuelve_la_respuesta_configurada() -> None:
    fija = {"recomendaciones": ["Acude a emergencia."], "fuentes": ["F2"]}
    llm = ProveedorLLMFalso(respuesta=fija)
    assert await llm.completar_json("sistema", "usuario") == fija
    assert llm.llamadas == [("sistema", "usuario")]


def test_sin_variables_de_azure_se_usan_los_falsos() -> None:
    settings = Settings(
        jwt_secret="x" * 32,
        internal_api_key="y" * 32,
        keyvault_url=None,
        azure_openai_endpoint=None,
    )
    assert isinstance(crear_proveedor_claves(settings), ProveedorClavesFalso)
    assert isinstance(crear_proveedor_llm(settings), ProveedorLLMFalso)


async def test_llm_falso_sin_respuesta_fija_contesta_segun_la_severidad() -> None:
    from app.modules.orientacion.esquemas import Severidad
    from app.modules.orientacion.servicio import REGLAS, SISTEMA, validar_respuesta_llm

    llm = ProveedorLLMFalso()
    for severidad in Severidad:
        crudo = await llm.completar_json(SISTEMA.format(severidad=severidad.value), "")
        validar_respuesta_llm(crudo, severidad, {"F1"}, REGLAS)  # no lanza
