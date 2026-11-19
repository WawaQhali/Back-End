"""Tablas del modulo modelos, en el esquema `modelos` de PostgreSQL."""

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Float, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db import Base


class VersionModelo(Base):
    __tablename__ = "versiones"
    __table_args__ = {"schema": "modelos"}

    version: Mapped[str] = mapped_column(String(50), primary_key=True)
    sensibilidad: Mapped[float] = mapped_column(Float)
    sha256: Mapped[str] = mapped_column(String(64))
    blob_path: Mapped[str] = mapped_column(String(300))  # modelos/...
    tamano: Mapped[int] = mapped_column(BigInteger)
    entrada: Mapped[dict[str, Any]] = mapped_column(JSONB)
    clases: Mapped[list[str]] = mapped_column(JSONB)
    umbral_confianza: Mapped[float] = mapped_column(Float)
    # candidato | publicado | bloqueado | retirado
    estado: Mapped[str] = mapped_column(String(20), index=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    publicado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
