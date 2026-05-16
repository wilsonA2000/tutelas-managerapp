"""add acumulación de tutelas (v9.2)

Revision ID: v92_acumulacion
Revises: v544_email_thr
Create Date: 2026-05-15

Añade a `cases` los campos para modelar acumulación procesal de tutelas y de
incidentes de desacato (Decreto 2591/1991 art. 13 + CGP art. 159 supletorio).

Cuando un juez ordena acumular dos o más expedientes, uno actúa como RECTOR
(recibe los demás) y los otros como ACUMULADO. Los acumulados mantienen su
rad/folder propios pero quedan vinculados al rector para efectos procesales
y de presentación en el cuadro:

  - acumulado_a_case_id (FK cases.id, nullable)  — apunta al rector
  - tipo_acumulacion (str: 'RECTOR' / 'ACUMULADO' / NULL)
  - acumulacion_auto_doc_id (FK documents.id, nullable) — el auto del juez
  - acumulacion_fecha (str DD/MM/AAAA)

NOTA: la DB de producción ya tenía las columnas (agregadas con ALTER TABLE
directo el 2026-05-15). Esta migración es para mantener el historial alembic.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "v92_acumulacion"
down_revision: Union[str, Sequence[str], None] = "v544_email_thr"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("cases", schema=None) as batch_op:
        batch_op.add_column(sa.Column("acumulado_a_case_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("tipo_acumulacion", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("acumulacion_auto_doc_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("acumulacion_fecha", sa.String(), nullable=True))
        batch_op.create_foreign_key(
            "fk_cases_acumulado_a_case_id", "cases",
            ["acumulado_a_case_id"], ["id"],
        )
        batch_op.create_foreign_key(
            "fk_cases_acumulacion_auto_doc_id", "documents",
            ["acumulacion_auto_doc_id"], ["id"],
        )

    op.create_index("ix_cases_acumulado_a_case_id", "cases", ["acumulado_a_case_id"])
    op.create_index("ix_cases_tipo_acumulacion", "cases", ["tipo_acumulacion"])


def downgrade() -> None:
    op.drop_index("ix_cases_tipo_acumulacion", table_name="cases")
    op.drop_index("ix_cases_acumulado_a_case_id", table_name="cases")
    with op.batch_alter_table("cases", schema=None) as batch_op:
        batch_op.drop_constraint("fk_cases_acumulacion_auto_doc_id", type_="foreignkey")
        batch_op.drop_constraint("fk_cases_acumulado_a_case_id", type_="foreignkey")
        batch_op.drop_column("acumulacion_fecha")
        batch_op.drop_column("acumulacion_auto_doc_id")
        batch_op.drop_column("tipo_acumulacion")
        batch_op.drop_column("acumulado_a_case_id")
