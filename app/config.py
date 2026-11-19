"""Configuracion leida de variables de entorno (seccion 10 de la guia)."""

from functools import lru_cache
from typing import Annotated

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # PostgreSQL. En Azure se entra con identidad gestionada (sin DB_PASSWORD).
    # DB_PORT y DB_PASSWORD solo se usan en local y en el CI (ver docs/decisiones.md).
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "wawa"
    db_user: str = "wawa"
    db_password: SecretStr | None = None

    # Sin ninguna de las dos se usa un Blob en memoria. STORAGE_CONNECTION_STRING solo
    # se usa en local con Azurite ("UseDevelopmentStorage=true"); en Azure, identidad
    # gestionada con STORAGE_ACCOUNT_URL.
    storage_account_url: str | None = None
    storage_connection_string: SecretStr | None = None

    # Si KEYVAULT_URL no esta definida se usa el ProveedorClaves falso.
    keyvault_url: str | None = None
    donation_key_name: str = "wawa-donaciones"

    # Si AZURE_OPENAI_ENDPOINT no esta definida se usa el ProveedorLLM falso.
    azure_openai_endpoint: str | None = None
    azure_openai_chat_deployment: str | None = None
    azure_openai_embedding_deployment: str | None = None

    jwt_secret: SecretStr = Field(min_length=32)
    internal_api_key: SecretStr = Field(min_length=32)

    cors_origins: Annotated[list[str], NoDecode] = []
    log_level: str = "INFO"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _separar_origenes(cls, valor: object) -> object:
        if isinstance(valor, str):
            return [o.strip() for o in valor.split(",") if o.strip()]
        return valor

    @property
    def usa_identidad_gestionada_bd(self) -> bool:
        return self.db_password is None


@lru_cache
def obtener_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # los valores llegan del entorno
