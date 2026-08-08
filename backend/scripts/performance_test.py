"""Generate test Excel files and run performance tests."""
import sys
import os
import time
from io import BytesIO
from decimal import Decimal
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from openpyxl import Workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.services.excel_import import import_excel
from app.services.shipment_service import create_shipment
from app.services.scan_service import process_scan
from app.services.lookup_cache import lookup_cache


def generate_excel(num_rows: int) -> bytes:
    wb = Workbook(write_only=True)
    ws = wb.create_sheet()
    ws.append(["ETİKET", "REFERANS", "MİKTAR", "X98FIFO_TARIH"])

    base_date = datetime(2026, 1, 1)
    refs = [f"REF-{i % 100}" for i in range(100)]

    for i in range(num_rows):
        label = f"700{i:07d}"
        ref = refs[i % 100]
        qty = 30
        fifo = base_date + timedelta(days=i % 365)
        ws.append([label, ref, qty, fifo.strftime("%d.%m.%Y %H:%M")])

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def run_performance_test(num_rows: int):
    print(f"\n{'='*60}")
    print(f"PERFORMANS TESTİ: {num_rows:,} etiket")
    print(f"{'='*60}")

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    lookup_cache._pools.clear()
    lookup_cache._label_data.clear()
    lookup_cache._all_labels.clear()

    excel = generate_excel(num_rows)
    print(f"Excel oluşturuldu: {len(excel)/1024/1024:.1f} MB")

    t0 = time.time()
    result = import_excel(db, excel)
    import_time = time.time() - t0
    print(f"Import: {result.successful:,} kayıt, {import_time:.2f}s ({result.successful/import_time:.0f} kayıt/s)")

    lookup_cache.reload_inventory_labels(db)

    t0 = time.time()
    shipment = create_shipment(db, "REF-0", Decimal("3000"))
    ship_time = time.time() - t0
    print(f"Sevkiyat oluşturma: {shipment.label_count} etiket, {ship_time:.3f}s")

    sid = shipment.shipment_id
    latencies = []

    test_labels = [f"700{i:07d}" for i in range(min(100, shipment.label_count))]
    for label in test_labels:
        t0 = time.time()
        process_scan(db, sid, label)
        latencies.append((time.time() - t0) * 1000)

    avg_lat = sum(latencies) / len(latencies)
    max_lat = max(latencies)
    print(f"Scan lookup: avg={avg_lat:.2f}ms, max={max_lat:.2f}ms ({len(latencies)} okutma)")

    t0 = time.time()
    for i in range(1000):
        lookup_cache.lookup(sid, f"700{i:07d}")
    lookup_time = (time.time() - t0) * 1000
    print(f"Memory lookup (1000x): {lookup_time:.2f}ms total, {lookup_time/1000:.3f}ms avg")

    db.close()
    print(f"SONUÇ: {'PASS' if avg_lat < 50 else 'WARN'} (hedef <50ms avg)")

    return {
        "rows": num_rows,
        "import_time": import_time,
        "import_rate": result.successful / import_time,
        "ship_time": ship_time,
        "avg_scan_ms": avg_lat,
        "max_scan_ms": max_lat,
        "lookup_1000_ms": lookup_time,
    }


if __name__ == "__main__":
    sizes = [10000, 50000, 100000]
    if len(sys.argv) > 1:
        sizes = [int(sys.argv[1])]

    results = []
    for size in sizes:
        try:
            r = run_performance_test(size)
            results.append(r)
        except Exception as e:
            print(f"HATA ({size}): {e}")

    print(f"\n{'='*60}")
    print("ÖZET")
    print(f"{'='*60}")
    for r in results:
        print(f"  {r['rows']:,} etiket: import={r['import_time']:.1f}s, scan_avg={r['avg_scan_ms']:.1f}ms")
