"""Tablas del modulo recepcion, en el esquema `recepcion` de PostgreSQL."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db import Base


class Paquete(Base):
    __tablename__ = "paquetes"
    __table_args__ = {"schema": "recepcion"}

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    installation_id: Mapped[uuid.UUID] = mapped_column(index=True)
    blob_path: Mapped[str] = mapped_column(String(300))  # cuarentena/{installation_id}/{id}.json
    kid: Mapped[str] = mapped_column(String(500))
    recibido_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    eliminado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
