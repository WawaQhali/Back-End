"""Cifrado hibrido de las donaciones (seccion 6.5, OE4-I4). Sin base de datos."""

import uuid

import pytest
from cryptography.exceptions import InvalidTag

from tests.ayudas import armar_paquete, contenido_donado, descifrar_paquete


@pytest.fixture
async def jwk(claves) -> dict:  # noqa: ANN001
    return (await claves.clave_publica()).model_dump()


async def test_ida_y_vuelta_con_el_formato_de_la_app(claves, jwk: dict) -> None:  # noqa: ANN001
    instalacion = uuid.uuid4()
    contenido = contenido_donado()
    paquete = armar_paquete(jwk, instalacion, contenido)
    assert descifrar_paquete(paquete, instalacion, claves) == contenido


async def test_con_otro_installation_id_el_descifrado_falla(claves, jwk: dict) -> None:  # noqa: ANN001
    paquete = armar_paquete(jwk, uuid.uuid4(), contenido_donado())
    with pytest.raises(InvalidTag):
        descifrar_paquete(paquete, uuid.uuid4(), claves)


async def test_mgf1_con_sha1_no_se_puede_desenvolver(claves, jwk: dict) -> None:  # noqa: ANN001
    """El "error tipico" de 6.2: RSA-OAEP con SHA-1 en MGF1 no coincide con Key Vault."""
    import base64

    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding, rsa

    from tests.ayudas import _entero

    publica = rsa.RSAPublicNumbers(_entero(jwk["e"]), _entero(jwk["n"])).public_key()
    con_sha1 = padding.OAEP(
        mgf=padding.MGF1(algorithm=hashes.SHA1()),  # noqa: S303
        algorithm=hashes.SHA256(),
        label=None,
    )
    envuelta = publica.encrypt(b"k" * 32, con_sha1)
    with pytest.raises(ValueError):
        claves.desenvolver_para_pruebas(base64.b64decode(base64.b64encode(envuelta)))
