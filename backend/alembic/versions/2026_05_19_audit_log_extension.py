"""extend audit_log with entity_type, entity_id, description, meta_json

Revision ID: v95_audit_log_extension
Revises: v94_compliance_ordenes
Create Date: 2026-05-19

Extiende `audit_log` (780 filas existentes preservadas) con 4 columnas para
soportar el "Historial del expediente" requerido por Wilson — auditoría
completa desde la génesis del expediente hasta su finalización.

Nuevas columnas:
  - entity_type        — case|document|email|compliance|field (a qué se refiere
                         el evento; hoy todo apunta a case_id, ahora podemos
                         decir explícitamente "es un cambio sobre compliance#286")
  - entity_id          — id del objeto específico (ej. compliance_tracking.id,
                         document.id, email.id). Complementa case_id.
  - description        — frase human-readable que aparece en la UI del modal
                         (ej. "Estado cambiado VENCIDO → EN_PROCESO").
                         Si está vacía, la UI usa action/old/new para construirla.
  - meta_json          — contexto adicional en JSON (ej. ordinal_nombre,
                         doc_id, email_id, source pdf, etc.).

Las columnas existentes (case_id, field_name, old_value, new_value, action,
source, timestamp) no se tocan. Las 780 filas históricas siguen siendo válidas.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "v95_audit_log_extension"
down_revision: Union[str, Sequence[str], None] = "v94_compliance_ordenes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("audit_log", schema=None) as batch_op:
        batch_op.add_column(sa.Column("entity_type", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("entity_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("description", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("meta_json", sa.Text(), nullable=True))
        # Índice compuesto para queries del modal Historial por case ordenado por fecha
        batch_op.create_index("ix_audit_log_case_ts", ["case_id", "timestamp"])


def downgrade() -> None:
    with op.batch_alter_table("audit_log", schema=None) as batch_op:
        batch_op.drop_index("ix_audit_log_case_ts")
        batch_op.drop_column("meta_json")
        batch_op.drop_column("description")
        batch_op.drop_column("entity_id")
        batch_op.drop_column("entity_type")
