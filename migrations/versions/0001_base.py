"""Base: extension vector, un esquema por modulo y la tabla shared.eventos.

Revision: 0001
Anterior:
Fecha: 2026-11-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ESQUEMAS = ("shared", "autorizacion", "recepcion", "revision", "modelos", "rag")


def upgrade() -> None:
    # En Azure, VECTOR debe estar en la lista azure.extensions del servidor.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    for esquema in ESQUEMAS:
        op.execute(f"CREATE SCHEMA IF NOT EXISTS {esquema}")

    op.create_table(
        "eventos",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tipo", sa.String(length=100), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "creado_en",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "procesado_por",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_eventos")),
        schema="shared",
    )
    op.create_index(op.f("ix_shared_eventos_tipo"), "eventos", ["tipo"], schema="shared")


def downgrade() -> None:
    op.drop_index(op.f("ix_shared_eventos_tipo"), table_name="eventos", schema="shared")
    op.drop_table("eventos", schema="shared")
    for esquema in reversed(ESQUEMAS):
        op.execute(f"DROP SCHEMA IF EXISTS {esquema}")
    # La extension vector se deja instalada: puede usarla otra base del servidor.
