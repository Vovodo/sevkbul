"""
Yerel SQLite (sevkiyat.db) verilerini ve aktif Excel dosyalarını (Mini S3)
uzak PostgreSQL sunucusundaki izole 'sevkbul' veritabanına aktarır.
Diğer uygulamanın bulunduğu 'postgres' veritabanına hiçbir şekilde dokunmaz.
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import app.models as models
from app.database import Base
from app.services.s3_storage import put_excel_object

PG_URL = "postgresql://postgres:7LcPCBpbZBtQqrv8HT4jJE6q5SK0C7z3OxVQoQnByl0Z9j052Yxgpp5agIjxgtus@213.142.148.57:5432/sevkbul"


def main() -> None:
    pg_engine = create_engine(PG_URL, pool_pre_ping=True)
    Base.metadata.create_all(bind=pg_engine)
    PgSession = sessionmaker(bind=pg_engine)
    pg_db = PgSession()

    sqlite_path = Path(__file__).resolve().parent.parent / "sevkiyat.db"
    if sqlite_path.is_file():
        sq = sqlite3.connect(str(sqlite_path))
        sq.row_factory = sqlite3.Row

        # 1. inventory_labels
        if pg_db.query(models.InventoryLabel).count() == 0:
            inv_rows = [dict(r) for r in sq.execute("SELECT * FROM inventory_labels").fetchall()]
            for r in inv_rows:
                r["blocked"] = bool(r["blocked"])
                r["hidden"] = bool(r["hidden"])
            if inv_rows:
                pg_db.bulk_insert_mappings(models.InventoryLabel, inv_rows)
                pg_db.commit()
            print(f"Migrated inventory_labels: {len(inv_rows)}")

        # 2. shipments
        if pg_db.query(models.Shipment).count() == 0:
            sh_rows = [dict(r) for r in sq.execute("SELECT * FROM shipments").fetchall()]
            for r in sh_rows:
                r["hourly_fifo"] = bool(r["hourly_fifo"])
                r["status"] = models.ShipmentStatus(r["status"].lower())
            if sh_rows:
                pg_db.bulk_insert_mappings(models.Shipment, sh_rows)
                pg_db.commit()
            print(f"Migrated shipments: {len(sh_rows)}")

        # 3. shipment_labels
        if pg_db.query(models.ShipmentLabel).count() == 0:
            sl_rows = [dict(r) for r in sq.execute("SELECT * FROM shipment_labels").fetchall()]
            for r in sl_rows:
                r["status"] = models.ShipmentLabelStatus(r["status"].lower())
            if sl_rows:
                pg_db.bulk_insert_mappings(models.ShipmentLabel, sl_rows)
                pg_db.commit()
            print(f"Migrated shipment_labels: {len(sl_rows)}")

        # 4. shipment_date_quotas
        if pg_db.query(models.ShipmentDateQuota).count() == 0:
            q_rows = [dict(r) for r in sq.execute("SELECT * FROM shipment_date_quotas").fetchall()]
            if q_rows:
                pg_db.bulk_insert_mappings(models.ShipmentDateQuota, q_rows)
                pg_db.commit()
            print(f"Migrated shipment_date_quotas: {len(q_rows)}")

        # 5. scan_logs
        if pg_db.query(models.ScanLog).count() == 0:
            log_rows = [dict(r) for r in sq.execute("SELECT * FROM scan_logs").fetchall()]
            for r in log_rows:
                st = r["result"]
                r["result"] = getattr(models.ScanResult, st) if hasattr(models.ScanResult, st) else models.ScanResult(st)
            if log_rows:
                pg_db.bulk_insert_mappings(models.ScanLog, log_rows)
                pg_db.commit()
            print(f"Migrated scan_logs: {len(log_rows)}")

        sq.close()

    # 6. Sequence güncellemesi
    tables = (
        "inventory_labels",
        "shipments",
        "shipment_labels",
        "shipment_date_quotas",
        "scan_logs",
        "shipment_targets",
        "excel_header_settings",
        "stored_excel_files",
    )
    with pg_engine.begin() as conn:
        for tbl in tables:
            conn.execute(
                text(
                    f"SELECT setval(pg_get_serial_sequence('{tbl}', 'id'), "
                    f"COALESCE((SELECT MAX(id) FROM {tbl}), 1), "
                    f"(SELECT MAX(id) IS NOT NULL FROM {tbl}))"
                )
            )

    # 7. Mini S3 başlangıç Excel dosyalarını yükle
    root_dir = Path(__file__).resolve().parent.parent.parent
    stock_file = root_dir / "Test_Stok_40_Referans_3200_Etiket.xlsx"
    if stock_file.is_file():
        s_obj = put_excel_object(pg_db, "stock", stock_file.name, stock_file.read_bytes(), row_count=3200)
        print(f"Stored stock Excel in Mini S3: {s_obj.storage_key} ({s_obj.size_bytes} bytes)")

    ship_file = root_dir / "Test_Sevkiyat_40_Referans.xlsx"
    if ship_file.is_file():
        sh_obj = put_excel_object(pg_db, "shipment", ship_file.name, ship_file.read_bytes(), row_count=40)
        print(f"Stored shipment Excel in Mini S3: {sh_obj.storage_key} ({sh_obj.size_bytes} bytes)")

    pg_db.close()
    print("PostgreSQL 'sevkbul' migration and Mini S3 setup complete!")


if __name__ == "__main__":
    main()
