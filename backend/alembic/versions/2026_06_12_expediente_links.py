"""tabla expediente_links — links al expediente OneDrive del juzgado

Revision ID: v98_expediente_links
Revises: v97_doc_created_at
Create Date: 2026-06-12

Los correos de notificación traen links al expediente digital del juzgado
(OneDrive cendoj). El path compartido contiene el rad VERDADERO (corrige typos
del subject — caso real e2038/c575) y la carpeta completa es descargable con
cookie FedAuth anónima (PoC validado). Esta tabla es la cola de cosecha,
resolución y descarga (ver email/expediente_links.py + services/expediente_fetcher.py).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "v98_expediente_links"
down_revision: Union[str, Sequence[str], None] = "v97_doc_created_at"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "expediente_links",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("url_kind", sa.String(), server_default=""),
        sa.Column("case_id", sa.Integer(), sa.ForeignKey("cases.id"), nullable=True),
        sa.Column("email_id", sa.Integer(), sa.ForeignKey("emails.id"), nullable=True),
        sa.Column("owner", sa.String(), server_default=""),
        sa.Column("juzgado_hint", sa.String(), server_default=""),
        sa.Column("server_path", sa.String(), server_default=""),
        sa.Column("rad23_url", sa.String(), server_default=""),
        sa.Column("etapa", sa.String(), server_default=""),
        sa.Column("instancia_hint", sa.String(), server_default=""),
        sa.Column("archivado", sa.Boolean(), server_default=sa.text("0")),
        sa.Column("estado", sa.String(), server_default="PENDIENTE"),
        sa.Column("last_checked", sa.DateTime(), nullable=True),
        sa.Column("n_files", sa.Integer(), server_default=sa.text("0")),
        sa.Column("n_descargados", sa.Integer(), server_default=sa.text("0")),
        sa.Column("error_detail", sa.String(), server_default=""),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_expediente_links_url", "expediente_links", ["url"], unique=True)
    op.create_index("ix_expediente_links_case_id", "expediente_links", ["case_id"])
    op.create_index("ix_expediente_links_email_id", "expediente_links", ["email_id"])
    op.create_index("ix_expediente_links_rad23_url", "expediente_links", ["rad23_url"])
    op.create_index("ix_expediente_links_estado", "expediente_links", ["estado"])


def downgrade() -> None:
    op.drop_table("expediente_links")
