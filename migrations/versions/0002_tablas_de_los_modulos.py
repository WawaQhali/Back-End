"""Tablas de los modulos: autorizacion, recepcion, revision, modelos y rag.

Revision: 0002
Anterior: 0001
Fecha: 2026-11-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "autorizaciones",
        sa.Column("installation_id", sa.Uuid(), nullable=False),
        sa.Column("version_texto", sa.String(length=20), nullable=False),
        sa.Column("otorgada_en", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revocada_en", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("installation_id", name=op.f("pk_autorizaciones")),
        schema="autorizacion",
    )
    op.create_table(
        "versiones",
        sa.Column("version", sa.String(length=50), nullable=False),
        sa.Column("sensibilidad", sa.Float(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("blob_path", sa.String(length=300), nullable=False),
        sa.Column("tamano", sa.BigInteger(), nullable=False),
        sa.Column("entrada", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("clases", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("umbral_confianza", sa.Float(), nullable=False),
        sa.Column("estado", sa.String(length=20), nullable=False),
        sa.Column(
            "creado_en", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("publicado_en", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("version", name=op.f("pk_versiones")),
        schema="modelos",
    )
    op.create_index(
        op.f("ix_modelos_versiones_estado"), "versiones", ["estado"], unique=False, schema="modelos"
    )
    op.create_table(
        "fragmentos",
        sa.Column("id", sa.String(length=200), nullable=False),
        sa.Column("documento", sa.String(length=300), nullable=False),
        sa.Column("fuente", sa.String(length=300), nullable=False),
        sa.Column("texto", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(dim=1536), nullable=False),
        sa.Column(
            "creado_en", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fragmentos")),
        schema="rag",
    )
    op.create_index(
        op.f("ix_rag_fragmentos_documento"), "fragmentos", ["documento"], unique=False, schema="rag"
    )
    op.create_index(
        "ix_rag_fragmentos_embedding_hnsw",
        "fragmentos",
        ["embedding"],
        unique=False,
        schema="rag",
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_table(
        "paquetes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("installation_id", sa.Uuid(), nullable=False),
        sa.Column("blob_path", sa.String(length=300), nullable=False),
        sa.Column("kid", sa.String(length=500), nullable=False),
        sa.Column(
            "recibido_en",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("eliminado_en", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_paquetes")),
        schema="recepcion",
    )
    op.create_index(
        op.f("ix_recepcion_paquetes_installation_id"),
        "paquetes",
        ["installation_id"],
        unique=False,
        schema="recepcion",
    )
    op.create_table(
        "imagenes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("paquete_id", sa.Uuid(), nullable=False),
        sa.Column("installation_id", sa.Uuid(), nullable=False),
        sa.Column("blob_path", sa.String(length=300), nullable=False),
        sa.Column("etiqueta_preliminar", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("etiqueta_final", sa.String(length=20), nullable=True),
        sa.Column("comentario", sa.Text(), nullable=True),
        sa.Column("revisada_por", sa.String(length=100), nullable=True),
        sa.Column("revisada_en", sa.DateTime(timezone=True), nullable=True),
        sa.Column("usada_en_modelo", sa.String(length=50), nullable=True),
        sa.Column("estado", sa.String(length=20), nullable=False),
        sa.Column(
            "creado_en", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_imagenes")),
        sa.UniqueConstraint("paquete_id", name=op.f("uq_imagenes_paquete_id")),
        schema="revision",
    )
    op.create_index(
        op.f("ix_revision_imagenes_estado"), "imagenes", ["estado"], unique=False, schema="revision"
    )
    op.create_index(
        op.f("ix_revision_imagenes_installation_id"),
        "imagenes",
        ["installation_id"],
        unique=False,
        schema="revision",
    )
    op.create_index(
        op.f("ix_revision_imagenes_revisada_en"),
        "imagenes",
        ["revisada_en"],
        unique=False,
        schema="revision",
    )
    op.create_table(
        "usuarios",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("usuario", sa.String(length=100), nullable=False),
        sa.Column("hash_contrasena", sa.String(length=200), nullable=False),
        sa.Column("rol", sa.String(length=20), nullable=False),
        sa.Column("activo", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_usuarios")),
        sa.UniqueConstraint("usuario", name=op.f("uq_usuarios_usuario")),
        schema="revision",
    )


def downgrade() -> None:
    op.drop_table("usuarios", schema="revision")
    op.drop_index(
        op.f("ix_revision_imagenes_revisada_en"), table_name="imagenes", schema="revision"
    )
    op.drop_index(
        op.f("ix_revision_imagenes_installation_id"), table_name="imagenes", schema="revision"
    )
    op.drop_index(op.f("ix_revision_imagenes_estado"), table_name="imagenes", schema="revision")
    op.drop_table("imagenes", schema="revision")
    op.drop_index(
        op.f("ix_recepcion_paquetes_installation_id"), table_name="paquetes", schema="recepcion"
    )
    op.drop_table("paquetes", schema="recepcion")
    op.drop_index(
        "ix_rag_fragmentos_embedding_hnsw",
        table_name="fragmentos",
        schema="rag",
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.drop_index(op.f("ix_rag_fragmentos_documento"), table_name="fragmentos", schema="rag")
    op.drop_table("fragmentos", schema="rag")
    op.drop_index(op.f("ix_modelos_versiones_estado"), table_name="versiones", schema="modelos")
    op.drop_table("versiones", schema="modelos")
    op.drop_table("autorizaciones", schema="autorizacion")
