"""Tablas del modulo revision, en el esquema `revision` de PostgreSQL."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db import Base


class Imagen(Base):
    __tablename__ = "imagenes"
    __table_args__ = {"schema": "revision"}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    paquete_id: Mapped[uuid.UUID] = mapped_column(unique=True)  # sin FK: otro esquema
    installation_id: Mapped[uuid.UUID] = mapped_column(index=True)
    blob_path: Mapped[str] = mapped_column(String(300))  # verificadas/...
    etiqueta_preliminar: Mapped[dict[str, Any]] = mapped_column(JSONB)
    etiqueta_final: Mapped[str | None] = mapped_column(String(20))
    comentario: Mapped[str | None] = mapped_column(Text)
    revisada_por: Mapped[str | None] = mapped_column(String(100))  # id del usuario
    revisada_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    usada_en_modelo: Mapped[str | None] = mapped_column(String(50))  # version del modelo
    # pendiente | revisada | eliminada
    estado: Mapped[str] = mapped_column(String(20), index=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Usuario(Base):
    __tablename__ = "usuarios"
    __table_args__ = {"schema": "revision"}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    usuario: Mapped[str] = mapped_column(String(100), unique=True)
    hash_contrasena: Mapped[str] = mapped_column(String(200))
    rol: Mapped[str] = mapped_column(String(20))  # medico | equipo
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
