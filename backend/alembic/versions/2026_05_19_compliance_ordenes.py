"""add compliance order columns (extractor v2)

Revision ID: v94_compliance_ordenes
Revises: v93_abogado_incidente
Create Date: 2026-05-19

Reframe del módulo Seguimiento: `compliance_tracking` pasa de "plazos a vigilar"
a "órdenes a cumplir" (cardinalidad 1:N case→orden). Una sentencia favorable a
SED genera una fila por cada ordinal con orden sustantiva, independiente de si
tiene plazo numérico. Toda orden es exigible vía desacato (Decreto 2591/1991
Art. 27, 52).

Nuevas columnas:
  - ordinal_nombre        — PRIMERO/SEGUNDO/...
  - tipo_plazo            — NUMERICO|FECHA|INMEDIATO|PERMANENTE|CONDICIONAL|SIN_PLAZO
  - destinatario_tipo     — SED_DIRECTA|SED_VINCULADA|TERCERO_SED_VINCULADA|SED_OTRA
  - accion_resumida       — frase imperativa principal (≤250 chars)
  - condicion             — texto de la condición (tipo_plazo=CONDICIONAL)
  - verbo_orden           — ORDENAR|CONMINAR|REQUERIR|DISPONER|EXHORTAR|"(IMPLÍCITO)"
  - fecha_especifica      — DD/MM/YYYY cuando tipo_plazo=FECHA
  - evidencia_doc_id      — FK a documents (oficio respuesta SED que acredita cumplimiento)

Las columnas existentes (plazo_dias, fecha_limite, estado, fecha_cumplimiento,
notas) se preservan. Filas legacy quedan con los nuevos campos NULL hasta que
la re-extracción las migre.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "v94_compliance_ordenes"
down_revision: Union[str, Sequence[str], None] = "v93_abogado_incidente"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("compliance_tracking", schema=None) as batch_op:
        batch_op.add_column(sa.Column("ordinal_nombre", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("tipo_plazo", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("destinatario_tipo", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("accion_resumida", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("condicion", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("verbo_orden", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("fecha_especifica", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("evidencia_doc_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("compliance_tracking", schema=None) as batch_op:
        batch_op.drop_column("evidencia_doc_id")
        batch_op.drop_column("fecha_especifica")
        batch_op.drop_column("verbo_orden")
        batch_op.drop_column("condicion")
        batch_op.drop_column("accion_resumida")
        batch_op.drop_column("destinatario_tipo")
        batch_op.drop_column("tipo_plazo")
        batch_op.drop_column("ordinal_nombre")
