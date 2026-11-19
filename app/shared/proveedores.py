"""Interfaces ProveedorClaves y ProveedorLLM, con sus versiones falsas y de Azure.

Las falsas permiten correr todo en local y en las pruebas sin Azure (seccion 0 y 10).
Se elige la de Azure solo si su variable de entorno esta definida.
"""

import base64
import hashlib
import math
import re
from abc import ABC, abstractmethod
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any

import anyio
from pydantic import BaseModel

from app.config import Settings, obtener_settings

ALGORITMO_ENVOLTURA = "RSA-OAEP-256"
DIMENSION_EMBEDDING = 1536  # TODO(etapa 2): confirmar con el despliegue de embeddings
API_VERSION_AZURE_OPENAI = "2024-10-21"
TIEMPO_LIMITE_LLM_S = 15


def _b64url(numero: int) -> str:
    crudo = numero.to_bytes((numero.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(crudo).rstrip(b"=").decode()


class ClavePublicaJWK(BaseModel):
    kty: str = "RSA"
    n: str
    e: str
    kid: str
    alg: str = ALGORITMO_ENVOLTURA


# ---------------------------------------------------------------------------
# Claves (Key Vault)
# ---------------------------------------------------------------------------


class ProveedorClaves(ABC):
    """Solo lectura de la parte publica. El backend nunca descifra (seccion 6)."""

    @abstractmethod
    async def clave_publica(self) -> ClavePublicaJWK:
        """Version vigente de la clave, como JWK."""

    @abstractmethod
    async def kids_habilitados(self) -> set[str]:
        """Todas las versiones habilitadas (la vigente y las que aun vacian la cuarentena)."""


class ProveedorClavesFalso(ProveedorClaves):
    """Clave RSA 3072 generada en memoria. Para local y pruebas."""

    def __init__(self, nombre: str = "wawa-donaciones", version: str = "local1") -> None:
        from cryptography.hazmat.primitives.asymmetric import rsa

        self._privada = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        self.kid = f"https://local.vault.invalid/keys/{nombre}/{version}"

    async def clave_publica(self) -> ClavePublicaJWK:
        numeros = self._privada.public_key().public_numbers()
        return ClavePublicaJWK(n=_b64url(numeros.n), e=_b64url(numeros.e), kid=self.kid)

    async def kids_habilitados(self) -> set[str]:
        return {self.kid}

    def desenvolver_para_pruebas(self, clave_cifrada: bytes) -> bytes:
        """Imita el unwrapKey de Key Vault. Solo lo usan las pruebas de ida y vuelta."""
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding

        relleno = padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None
        )
        return self._privada.decrypt(clave_cifrada, relleno)


class ProveedorClavesAzure(ProveedorClaves):
    """Key Vault con identidad gestionada. Permiso necesario: keys/get y keys/list."""

    def __init__(self, vault_url: str, nombre_clave: str) -> None:
        from azure.identity import DefaultAzureCredential
        from azure.keyvault.keys import KeyClient

        self._cliente = KeyClient(vault_url=vault_url, credential=DefaultAzureCredential())
        self._nombre = nombre_clave

    async def clave_publica(self) -> ClavePublicaJWK:
        clave = await anyio.to_thread.run_sync(self._cliente.get_key, self._nombre)
        jwk = clave.key
        return ClavePublicaJWK(
            n=base64.urlsafe_b64encode(jwk.n).rstrip(b"=").decode(),
            e=base64.urlsafe_b64encode(jwk.e).rstrip(b"=").decode(),
            kid=str(clave.id),
        )

    async def kids_habilitados(self) -> set[str]:
        def _listar() -> set[str]:
            versiones = self._cliente.list_properties_of_key_versions(self._nombre)
            return {str(v.id) for v in versiones if v.enabled}

        return await anyio.to_thread.run_sync(_listar)


# ---------------------------------------------------------------------------
# LLM y embeddings (Azure OpenAI)
# ---------------------------------------------------------------------------


class ProveedorLLM(ABC):
    @abstractmethod
    async def embeddings(self, textos: list[str]) -> list[list[float]]:
        """Un vector por texto."""

    @abstractmethod
    async def completar_json(self, sistema: str, usuario: str) -> dict[str, Any]:
        """Temperatura 0, salida JSON y limite de 15 s. Lanza excepcion si falla."""


class ProveedorLLMFalso(ProveedorLLM):
    """Embeddings deterministas por hash y una respuesta fija configurable."""

    RESPUESTA_POR_DEFECTO: dict[str, Any] = {
        "recomendaciones": ["Consulta con un profesional de salud."],
        "fuentes": ["F1"],
    }

    def __init__(self, respuesta: dict[str, Any] | None = None) -> None:
        self.respuesta = respuesta if respuesta is not None else dict(self.RESPUESTA_POR_DEFECTO)
        self.llamadas: list[tuple[str, str]] = []

    async def embeddings(self, textos: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in textos]

    async def completar_json(self, sistema: str, usuario: str) -> dict[str, Any]:
        self.llamadas.append((sistema, usuario))
        return self.respuesta

    @staticmethod
    def _vector(texto: str) -> list[float]:
        """Bolsa de palabras con hashing: textos con palabras en comun quedan cerca.
        Asi la busqueda por similitud del RAG tiene sentido tambien en local."""
        valores = [0.0] * DIMENSION_EMBEDDING
        palabras = re.findall(r"\w+", texto.lower()) or [""]
        for palabra in palabras:
            resumen = hashlib.sha256(palabra.encode()).digest()
            indice = int.from_bytes(resumen[:4], "big") % DIMENSION_EMBEDDING
            valores[indice] += 1.0 if resumen[4] % 2 == 0 else -1.0
        norma = math.sqrt(sum(v * v for v in valores)) or 1.0
        return [v / norma for v in valores]


class ProveedorLLMAzure(ProveedorLLM):
    """Azure OpenAI con identidad gestionada (sin claves)."""

    def __init__(self, endpoint: str, despliegue_chat: str, despliegue_embeddings: str) -> None:
        from azure.identity import DefaultAzureCredential, get_bearer_token_provider
        from openai import AsyncAzureOpenAI

        proveedor_token = get_bearer_token_provider(
            DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"
        )
        self._cliente = AsyncAzureOpenAI(
            azure_endpoint=endpoint,
            azure_ad_token_provider=proveedor_token,
            api_version=API_VERSION_AZURE_OPENAI,
            timeout=TIEMPO_LIMITE_LLM_S,
            max_retries=0,
        )
        self._chat = despliegue_chat
        self._embeddings = despliegue_embeddings

    async def embeddings(self, textos: list[str]) -> list[list[float]]:
        respuesta = await self._cliente.embeddings.create(model=self._embeddings, input=textos)
        return [d.embedding for d in respuesta.data]

    async def completar_json(self, sistema: str, usuario: str) -> dict[str, Any]:
        import json

        respuesta = await self._cliente.chat.completions.create(
            model=self._chat,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": sistema},
                {"role": "user", "content": usuario},
            ],
        )
        contenido = respuesta.choices[0].message.content or ""
        return json.loads(contenido)


# ---------------------------------------------------------------------------
# Blob Storage (contenedores cuarentena, verificadas y modelos)
# ---------------------------------------------------------------------------

DURACION_ENLACE = timedelta(minutes=5)


def separar_ruta(blob_path: str) -> tuple[str, str]:
    """'cuarentena/abc/1.json' -> ('cuarentena', 'abc/1.json')."""
    contenedor, _, nombre = blob_path.partition("/")
    if not contenedor or not nombre:
        raise ValueError("Ruta de blob sin contenedor")
    return contenedor, nombre


class ProveedorBlob(ABC):
    @abstractmethod
    async def subir(self, blob_path: str, datos: bytes, tipo: str) -> None:
        """Sube un blob nuevo. No sobrescribe."""

    @abstractmethod
    async def borrar(self, blob_path: str) -> None:
        """Borra el blob. Si no existe, no hace nada (idempotente)."""

    @abstractmethod
    async def enlace_lectura(self, blob_path: str) -> str:
        """SAS de solo lectura, un solo blob, que vence en 5 minutos (seccion 9)."""


class ProveedorBlobMemoria(ProveedorBlob):
    """Blob en memoria. Para pruebas y para correr en local sin Azurite."""

    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    async def subir(self, blob_path: str, datos: bytes, tipo: str) -> None:
        separar_ruta(blob_path)
        if blob_path in self.blobs:
            raise FileExistsError(blob_path)
        self.blobs[blob_path] = datos

    async def borrar(self, blob_path: str) -> None:
        self.blobs.pop(blob_path, None)

    async def enlace_lectura(self, blob_path: str) -> str:
        vence = (datetime.now(UTC) + DURACION_ENLACE).strftime("%Y-%m-%dT%H:%M:%SZ")
        return f"memoria://{blob_path}?se={vence}&sp=r"


class ProveedorBlobAzure(ProveedorBlob):
    """Azure Blob con identidad gestionada y SAS de delegacion de usuario.
    En local (Azurite) usa STORAGE_CONNECTION_STRING y SAS con la clave de la cuenta."""

    def __init__(self, account_url: str | None, connection_string: str | None) -> None:
        from azure.storage.blob import BlobServiceClient

        if connection_string:
            self._cliente = BlobServiceClient.from_connection_string(connection_string)
            self._clave_cuenta: str | None = self._cliente.credential.account_key
        else:
            from azure.identity import DefaultAzureCredential

            self._cliente = BlobServiceClient(account_url, credential=DefaultAzureCredential())
            self._clave_cuenta = None

    async def subir(self, blob_path: str, datos: bytes, tipo: str) -> None:
        from azure.core.exceptions import ResourceNotFoundError
        from azure.storage.blob import ContentSettings

        contenedor, nombre = separar_ruta(blob_path)

        def _subir() -> None:
            blob = self._cliente.get_blob_client(contenedor, nombre)
            ajustes = ContentSettings(content_type=tipo)
            try:
                blob.upload_blob(datos, overwrite=False, content_settings=ajustes)
            except ResourceNotFoundError:
                if self._clave_cuenta is None:  # en Azure los contenedores ya existen
                    raise
                self._cliente.create_container(contenedor)
                blob.upload_blob(datos, overwrite=False, content_settings=ajustes)

        await anyio.to_thread.run_sync(_subir)

    async def borrar(self, blob_path: str) -> None:
        from azure.core.exceptions import ResourceNotFoundError

        contenedor, nombre = separar_ruta(blob_path)

        def _borrar() -> None:
            try:
                self._cliente.get_blob_client(contenedor, nombre).delete_blob()
            except ResourceNotFoundError:
                pass

        await anyio.to_thread.run_sync(_borrar)

    async def enlace_lectura(self, blob_path: str) -> str:
        from azure.storage.blob import BlobSasPermissions, generate_blob_sas

        contenedor, nombre = separar_ruta(blob_path)
        inicio = datetime.now(UTC) - timedelta(minutes=1)
        vence = datetime.now(UTC) + DURACION_ENLACE

        def _enlace() -> str:
            cuenta = self._cliente.account_name
            permiso = BlobSasPermissions(read=True)
            if self._clave_cuenta:
                sas = generate_blob_sas(
                    cuenta,
                    contenedor,
                    nombre,
                    account_key=self._clave_cuenta,
                    permission=permiso,
                    start=inicio,
                    expiry=vence,
                )
            else:
                clave_delegada = self._cliente.get_user_delegation_key(inicio, vence)
                sas = generate_blob_sas(
                    cuenta,
                    contenedor,
                    nombre,
                    user_delegation_key=clave_delegada,
                    permission=permiso,
                    start=inicio,
                    expiry=vence,
                )
            return f"{self._cliente.get_blob_client(contenedor, nombre).url}?{sas}"

        return await anyio.to_thread.run_sync(_enlace)


# ---------------------------------------------------------------------------
# Seleccion segun la configuracion
# ---------------------------------------------------------------------------


def crear_proveedor_blob(settings: Settings) -> ProveedorBlob:
    cadena = settings.storage_connection_string
    if cadena or settings.storage_account_url:
        return ProveedorBlobAzure(
            settings.storage_account_url, cadena.get_secret_value() if cadena else None
        )
    return ProveedorBlobMemoria()


@lru_cache
def obtener_proveedor_blob() -> ProveedorBlob:
    """Dependencia de FastAPI y de los manejadores de eventos."""
    return crear_proveedor_blob(obtener_settings())


def crear_proveedor_claves(settings: Settings) -> ProveedorClaves:
    if settings.keyvault_url:
        return ProveedorClavesAzure(settings.keyvault_url, settings.donation_key_name)
    return ProveedorClavesFalso(nombre=settings.donation_key_name)


def crear_proveedor_llm(settings: Settings) -> ProveedorLLM:
    if settings.azure_openai_endpoint:
        if not (
            settings.azure_openai_chat_deployment and settings.azure_openai_embedding_deployment
        ):
            raise ValueError("Faltan AZURE_OPENAI_CHAT_DEPLOYMENT o _EMBEDDING_DEPLOYMENT")
        return ProveedorLLMAzure(
            settings.azure_openai_endpoint,
            settings.azure_openai_chat_deployment,
            settings.azure_openai_embedding_deployment,
        )
    return ProveedorLLMFalso()


@lru_cache
def obtener_proveedor_claves() -> ProveedorClaves:
    """Dependencia de FastAPI. Sin KEYVAULT_URL devuelve el falso (una sola instancia)."""
    return crear_proveedor_claves(obtener_settings())


@lru_cache
def obtener_proveedor_llm() -> ProveedorLLM:
    """Dependencia de FastAPI. Sin AZURE_OPENAI_ENDPOINT devuelve el falso."""
    return crear_proveedor_llm(obtener_settings())
