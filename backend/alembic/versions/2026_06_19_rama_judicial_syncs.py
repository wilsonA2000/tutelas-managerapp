"""tabla rama_judicial_syncs — cache + estado de sync con la API CPNU

Revision ID: v99_rama_judicial_syncs
Revises: v98_expediente_links
Create Date: 2026-06-19

Cache de la respuesta CPNU por radicado (proceso + actuaciones normalizadas) para
no re-pegar la API en cada extracción, + estado de sync y conteo de actuaciones
para detectar novedades (Fase C). Ver services/rama_judicial_client.py.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "v99_rama_judicial_syncs"
down_revision: Union[str, Sequence[str], None] = "v98_expediente_links"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "rama_judicial_syncs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("case_id", sa.Integer(), sa.ForeignKey("cases.id"), nullable=True),
        sa.Column("radicado_23_digitos", sa.String(), nullable=True),
        sa.Column("estado_sync", sa.String(), server_default="PENDIENTE"),
        sa.Column("expediente_json", sa.Text(), nullable=True),
        sa.Column("last_actuaciones_count", sa.Integer(), server_default=sa.text("0")),
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
        sa.Column("error_detail", sa.String(), server_default=""),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_rama_judicial_syncs_case_id", "rama_judicial_syncs", ["case_id"])
    op.create_index("ix_rama_judicial_syncs_radicado_23_digitos",
                    "rama_judicial_syncs", ["radicado_23_digitos"])
    op.create_index("ix_rama_judicial_syncs_estado_sync", "rama_judicial_syncs", ["estado_sync"])


def downgrade() -> None:
    op.drop_table("rama_judicial_syncs")
