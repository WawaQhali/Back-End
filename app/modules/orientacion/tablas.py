"""Tablas del modulo orientacion, en el esquema `rag` de PostgreSQL (fragmentos del RAG)."""

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db import Base
from app.shared.proveedores import DIMENSION_EMBEDDING


class Fragmento(Base):
    __tablename__ = "fragmentos"
    __table_args__ = (
        Index(
            "ix_rag_fragmentos_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        {"schema": "rag"},
    )

    # "<archivo>#<n>", p. ej. "guia-urticaria-pediatrica#3". Es lo que va en `fuentes`.
    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    documento: Mapped[str] = mapped_column(String(300), index=True)  # titulo
    fuente: Mapped[str] = mapped_column(String(300))  # organizacion y ano
    texto: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(DIMENSION_EMBEDDING))
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
