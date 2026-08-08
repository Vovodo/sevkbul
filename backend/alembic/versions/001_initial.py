"""Initial migration

Revision ID: 001
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "inventory_labels",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(100), nullable=False),
        sa.Column("reference", sa.String(200), nullable=False),
        sa.Column("quantity", sa.Numeric(12, 2), nullable=False),
        sa.Column("fifo_date", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_inventory_labels_id", "inventory_labels", ["id"])
    op.create_index("ix_inventory_labels_label", "inventory_labels", ["label"], unique=True)
    op.create_index("ix_inventory_labels_reference", "inventory_labels", ["reference"])
    op.create_index("ix_inventory_labels_fifo_date", "inventory_labels", ["fifo_date"])

    op.create_table(
        "shipments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("reference", sa.String(200), nullable=False),
        sa.Column("requested_quantity", sa.Numeric(12, 2), nullable=False),
        sa.Column("status", sa.Enum("ACTIVE", "COMPLETED", "CANCELLED", name="shipmentstatus"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_shipments_id", "shipments", ["id"])
    op.create_index("ix_shipments_reference", "shipments", ["reference"])
    op.create_index("ix_shipments_status", "shipments", ["status"])

    op.create_table(
        "shipment_labels",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("shipment_id", sa.Integer(), nullable=False),
        sa.Column("inventory_label_id", sa.Integer(), nullable=False),
        sa.Column("allocated_quantity", sa.Numeric(12, 2), nullable=False),
        sa.Column("scanned_quantity", sa.Numeric(12, 2), nullable=True),
        sa.Column("status", sa.Enum("PENDING", "SCANNED", "PARTIAL", name="shipmentlabelstatus"), nullable=True),
        sa.ForeignKeyConstraint(["inventory_label_id"], ["inventory_labels.id"]),
        sa.ForeignKeyConstraint(["shipment_id"], ["shipments.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_shipment_labels_id", "shipment_labels", ["id"])
    op.create_index("ix_shipment_labels_shipment_id", "shipment_labels", ["shipment_id"])
    op.create_index("ix_shipment_labels_shipment_inventory", "shipment_labels", ["shipment_id", "inventory_label_id"])

    op.create_table(
        "scan_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("shipment_id", sa.Integer(), nullable=True),
        sa.Column("inventory_label_id", sa.Integer(), nullable=True),
        sa.Column("scanned_value", sa.String(100), nullable=False),
        sa.Column("result", sa.Enum(
            "SEVKİYAT ÜRÜNÜ", "SEVKİYAT DIŞI", "ETİKET BULUNAMADI", "ZATEN OKUTULDU",
            name="scanresult"
        ), nullable=False),
        sa.Column("scanned_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["inventory_label_id"], ["inventory_labels.id"]),
        sa.ForeignKeyConstraint(["shipment_id"], ["shipments.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_scan_logs_id", "scan_logs", ["id"])
    op.create_index("ix_scan_logs_shipment_id", "scan_logs", ["shipment_id"])
    op.create_index("ix_scan_logs_scanned_at", "scan_logs", ["scanned_at"])
    op.create_index("ix_scan_logs_shipment_scanned_at", "scan_logs", ["shipment_id", "scanned_at"])


def downgrade() -> None:
    op.drop_table("scan_logs")
    op.drop_table("shipment_labels")
    op.drop_table("shipments")
    op.drop_table("inventory_labels")
    op.execute("DROP TYPE IF EXISTS scanresult")
    op.execute("DROP TYPE IF EXISTS shipmentlabelstatus")
    op.execute("DROP TYPE IF EXISTS shipmentstatus")
