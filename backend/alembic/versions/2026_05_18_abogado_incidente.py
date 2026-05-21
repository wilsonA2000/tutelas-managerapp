"""add abogado_incidente columns to cases (×3)

Revision ID: v93_abogado_incidente
Revises: v92_acumulacion
Create Date: 2026-05-18

Añade a `cases` los campos `abogado_incidente`, `abogado_incidente_2` y
`abogado_incidente_3` (paralelos a `responsable_desacato_*`).

Justificación (feedback Wilson 2026-05-18, mem feedback-incidente-desacato):

- `responsable_desacato` (existente) = funcionario público SANCIONABLE por el
  juez en el trámite incidental (típicamente Secretario/a de Educación,
  Gobernador, Director Administrativo). Es la noción del Decreto 2591/1991 y
  los autos judiciales nombran explícitamente.

- `abogado_incidente` (NUEVO) = abogado SED que opera la defensa procesal del
  incidente. Por convención interna, es el MISMO `abogado_responsable` que
  llevó la tutela (no hay reasignación). Se mantiene como columna propia para
  no corromper la semántica del campo jurídico `responsable_desacato`.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "v93_abogado_incidente"
down_revision: Union[str, Sequence[str], None] = "v92_acumulacion"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("cases", schema=None) as batch_op:
        batch_op.add_column(sa.Column("abogado_incidente", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("abogado_incidente_2", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("abogado_incidente_3", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("cases", schema=None) as batch_op:
        batch_op.drop_column("abogado_incidente_3")
        batch_op.drop_column("abogado_incidente_2")
        batch_op.drop_column("abogado_incidente")
