"""add_pii_mappings_and_privacy_stats (v5.3)

Revision ID: v53_pii_001
Revises: da5b8a5a7071
Create Date: 2026-04-21

Crea:
- cases.pii_mode (nullable)
- pii_mappings: token ↔ valor cifrado (Fernet) para rehidratación local
- privacy_stats: telemetría de la capa de anonimización
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "v53_pii_001"
down_revision: Union[str, Sequence[str], None] = "da5b8a5a7071"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("cases", schema=None) as batch_op:
        batch_op.add_column(sa.Column("pii_mode", sa.String(), nullable=True))

    op.create_table(
        "pii_mappings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("case_id", sa.Integer(), sa.ForeignKey("cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("value_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column("value_hash", sa.String(), nullable=False),
        sa.Column("meta_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("case_id", "token", name="uq_pii_case_token"),
    )
    op.create_index("ix_pii_mappings_case_id", "pii_mappings", ["case_id"])
    op.create_index("ix_pii_mappings_kind", "pii_mappings", ["kind"])
    op.create_index("ix_pii_mappings_value_hash", "pii_mappings", ["value_hash"])

    op.create_table(
        "privacy_stats",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("case_id", sa.Integer(), sa.ForeignKey("cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_at", sa.DateTime(), nullable=True),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("spans_detected", sa.Integer(), nullable=True),
        sa.Column("tokens_minted", sa.Integer(), nullable=True),
        sa.Column("violations_count", sa.Integer(), nullable=True),
        sa.Column("gate_blocked", sa.Boolean(), nullable=True),
        sa.Column("redactor_ms", sa.Integer(), nullable=True),
        sa.Column("rehydrator_ms", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
    )
    op.create_index("ix_privacy_stats_case_id", "privacy_stats", ["case_id"])
    op.create_index("ix_privacy_stats_run_at", "privacy_stats", ["run_at"])


def downgrade() -> None:
    op.drop_index("ix_privacy_stats_run_at", table_name="privacy_stats")
    op.drop_index("ix_privacy_stats_case_id", table_name="privacy_stats")
    op.drop_table("privacy_stats")

    op.drop_index("ix_pii_mappings_value_hash", table_name="pii_mappings")
    op.drop_index("ix_pii_mappings_kind", table_name="pii_mappings")
    op.drop_index("ix_pii_mappings_case_id", table_name="pii_mappings")
    op.drop_table("pii_mappings")

    with op.batch_alter_table("cases", schema=None) as batch_op:
        batch_op.drop_column("pii_mode")
