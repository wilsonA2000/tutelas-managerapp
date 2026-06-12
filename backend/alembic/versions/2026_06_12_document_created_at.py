"""add documents.created_at — ciclo de vida de extracción

Revision ID: v97_doc_created_at
Revises: v96_parte_resolutiva
Create Date: 2026-06-12

Añade `documents.created_at` (cuándo entró la fila a la DB). Comparado contra
`cases.field_confidences_json["v9_extracted_at"]` responde de forma DERIVADA
(sin estado manual que se desactualice): "¿este caso tiene documentos que
llegaron DESPUÉS de su última extracción?" — la pieza que faltaba para que el
módulo de extracción muestre candidatas (nunca extraídas) y desactualizadas
(docs nuevos sin extraer).

Backfill best-effort para filas existentes: fecha del email de origen
(emails.date_received) o, en su defecto, extraction_date. Las filas que quedan
NULL se tratan como "antiguas" (no disparan DESACTUALIZADO).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "v97_doc_created_at"
down_revision: Union[str, Sequence[str], None] = "v96_parte_resolutiva"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("documents", schema=None) as batch_op:
        batch_op.add_column(sa.Column("created_at", sa.DateTime(), nullable=True))
    # Backfill: fecha del email de origen > fecha de extracción de texto.
    op.execute(
        """
        UPDATE documents SET created_at = COALESCE(
            (SELECT e.date_received FROM emails e WHERE e.id = documents.email_id),
            documents.extraction_date
        )
        WHERE created_at IS NULL
        """
    )


def downgrade() -> None:
    with op.batch_alter_table("documents", schema=None) as batch_op:
        batch_op.drop_column("created_at")
