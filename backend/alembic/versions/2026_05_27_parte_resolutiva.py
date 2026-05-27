"""add parte_resolutiva_1st/2nd columns to cases

Revision ID: v96_parte_resolutiva
Revises: v95_audit_log_extension
Create Date: 2026-05-27

Añade a `cases` los campos `parte_resolutiva_1st` y `parte_resolutiva_2nd`
(Text), que guardan la TRANSCRIPCIÓN VERBATIM de la parte resolutiva del fallo
(el "RESUELVE…NOTIFÍQUESE/CÚMPLASE") de 1ra y 2da instancia.

Justificación (requisito del jurado 2026-05-27): el cuadro debe contener no solo
el `sentido_fallo_*` (clasificación CONCEDE/NIEGA) sino el texto literal del
resolutivo. Se llena de forma DETERMINISTA (regex sobre la zona dispositiva leída
del disco; 0 LLM — la transcripción literal no se delega a un modelo generativo).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "v96_parte_resolutiva"
down_revision: Union[str, Sequence[str], None] = "v95_audit_log_extension"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("cases", schema=None) as batch_op:
        batch_op.add_column(sa.Column("parte_resolutiva_1st", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("parte_resolutiva_2nd", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("cases", schema=None) as batch_op:
        batch_op.drop_column("parte_resolutiva_2nd")
        batch_op.drop_column("parte_resolutiva_1st")
