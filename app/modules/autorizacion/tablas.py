"""Tablas del modulo autorizacion, en el esquema `autorizacion` de PostgreSQL."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db import Base


class Autorizacion(Base):
    __tablename__ = "autorizaciones"
    __table_args__ = {"schema": "autorizacion"}

    installation_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    version_texto: Mapped[str] = mapped_column(String(20))
    otorgada_en: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revocada_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def vigente(self) -> bool:
        return self.revocada_en is None
