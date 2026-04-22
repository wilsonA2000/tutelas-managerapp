"""add email threading + match metadata (v5.4.4)

Revision ID: v544_email_thr
Revises: v53_pii_001
Create Date: 2026-04-22

Añade a `emails`:
- in_reply_to (String, indexed) — header RFC 5322 para threading de conversación
- `references` (Text) — cadena de message_ids de la conversación (RFC 5322)
- match_score (Integer) — score 0-100 del matcher multi-criterio
- match_signals_json (Text) — breakdown JSON de señales que contribuyeron al score
- match_confidence (String) — HIGH / MEDIUM / LOW / AMBIGUO

Motivación: sustituir el matching secuencial del monitor por scoring multi-criterio
con observabilidad. Emails con In-Reply-To que apunten a otro email ya procesado
pueden heredar case_id automáticamente (+50 score).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "v544_email_thr"
down_revision: Union[str, Sequence[str], None] = "v53_pii_001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("emails", schema=None) as batch_op:
        batch_op.add_column(sa.Column("in_reply_to", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("references_header", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("match_score", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("match_signals_json", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("match_confidence", sa.String(), nullable=True))

    op.create_index("ix_emails_in_reply_to", "emails", ["in_reply_to"])


def downgrade() -> None:
    op.drop_index("ix_emails_in_reply_to", table_name="emails")
    with op.batch_alter_table("emails", schema=None) as batch_op:
        batch_op.drop_column("match_confidence")
        batch_op.drop_column("match_signals_json")
        batch_op.drop_column("match_score")
        batch_op.drop_column("references_header")
        batch_op.drop_column("in_reply_to")
