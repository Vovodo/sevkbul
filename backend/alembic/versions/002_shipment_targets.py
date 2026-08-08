"""Add shipment_targets table

Revision ID: 002
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "shipment_targets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("reference", sa.String(200), nullable=False),
        sa.Column("target_quantity", sa.Numeric(12, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_shipment_targets_reference", "shipment_targets", ["reference"])


def downgrade() -> None:
    op.drop_table("shipment_targets")
