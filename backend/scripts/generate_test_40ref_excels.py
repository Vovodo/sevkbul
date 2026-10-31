"""
40 Referanslı, 3.200 Etiket Satırlık (Binlerce Kalem) Gerçekçi Stok Exceli
ve Paket/Koli Miktarlarına Tam Uyumlu Sevkiyat Exceli Üretici.
"""
from datetime import datetime, timedelta
from pathlib import Path
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

DESKTOP = Path(r"C:\Users\egepa\OneDrive\Desktop")
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# 40 farklı gerçekçi endüstriyel referans ve her referansın standart koli/paket miktarı
REFERENCES_WITH_PACK_SIZE = [
    ("6681401-HZN-1", 30),
    ("6681402-HZN-1", 30),
    ("6681403-HZE-1", 25),
    ("6681404-HZE-1", 25),
    ("6681405-HYC-1", 20),
    ("6681406-HYC-1", 20),
    ("6681407-HZN-1", 15),
    ("6681408-HZE-1", 15),
    ("6681409-HZN-1", 30),
    ("6681410-HYC-1", 40),
    ("6695301-HZE-1", 30),
    ("6695302-HZE-1", 30),
    ("6695303-HZN-1", 25),
    ("6695304-HZN-1", 20),
    ("6695305-FTG-1", 15),
    ("6695306-FTG-1", 10),
    ("6695307-FTG-1", 20),
    ("6695308-HYC-1", 30),
    ("6695309-HYC-1", 25),
    ("6695310-HZE-1", 40),
    ("5018701-FTG-1", 20),
    ("5018702-FTG-1", 20),
    ("5018703-HZN-1", 30),
    ("5018704-HZN-1", 30),
    ("5018705-HZE-1", 15),
    ("5018706-HZE-1", 15),
    ("5018707-HYC-1", 25),
    ("5018708-HYC-1", 25),
    ("5018709-FTG-1", 10),
    ("5018710-FTG-1", 10),
    ("6036101-G",     48),
    ("6036102-G",     48),
    ("6036103-G",     36),
    ("6036104-G",     36),
    ("6036105-G",     24),
    ("6036106-G",     24),
    ("6036107-G",     30),
    ("6036108-G",     30),
    ("6036109-G",     20),
    ("6036110-G",     20),
]

assert len(REFERENCES_WITH_PACK_SIZE) == 40


def build_stock_workbook() -> tuple[Workbook, dict[str, int]]:
    """
    40 referans × 80 etiket = 3.200 satırlık stok Exceli üretir.
    Her referans 16 farklı FIFO gününe (her günde 5 etiket) dağılır.
    Bazı etiketler test amaçlı BLOKAJ=DOĞRU olarak işaretlenir.
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "Stok_Listesi"

    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")

    headers = ["ETİKET", "REFERANS", "MİKTAR", "X98FIFO_TARIH", "BLOKAJ"]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = header_font
        cell.fill = header_fill

    base_date = datetime(2026, 5, 1, 8, 0)
    label_counter = 800010001
    total_stock_by_ref: dict[str, int] = {}

    # 16 farklı FIFO günü × 5 etiket/gün = referans başına 80 etiket (40 × 80 = 3.200 etiket!)
    for ref_idx, (ref_code, pack_qty) in enumerate(REFERENCES_WITH_PACK_SIZE):
        total_stock_by_ref[ref_code] = 0
        for day_idx in range(16):
            for box_idx in range(5):
                fifo_dt = base_date + timedelta(
                    days=day_idx * 2 + (ref_idx % 3),
                    hours=box_idx * 2,
                    minutes=(ref_idx * 7 + box_idx * 11) % 60,
                )
                # İlk 3 referansın 1. FIFO gününde (day_idx == 0) ve 4-5. referansların 2. FIFO gününde (day_idx == 1)
                # 1'er etiket BLOKAJLI (DOĞRU) olsun ki hem 1. sevkiyatta hem 2. sevkiyatta blokajlı FIFO tarihi test edilebilsin!
                is_blocked = (
                    (ref_idx < 3 and day_idx == 0 and box_idx == 2)
                    or (3 <= ref_idx < 5 and day_idx == 1 and box_idx == 2)
                )
                ws.append([
                    str(label_counter),
                    ref_code,
                    pack_qty,
                    fifo_dt.strftime("%d.%m.%Y %H:%M"),
                    "DOĞRU" if is_blocked else "YANLIŞ",
                ])
                label_counter += 1
                total_stock_by_ref[ref_code] += pack_qty

    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = 22

    return wb, total_stock_by_ref


def build_shipment_workbook() -> Workbook:
    """
    40 referansın her biri için stoktaki paket/koli miktarının (pack_qty)
    tam katı (örn. 12 koli, 15 koli, 20 koli) olan sevkiyat hedef listesi üretir.
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "Sevkiyat_Hedefleri"

    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="065F46", end_color="065F46", fill_type="solid")

    headers = ["REFERANS", "MİKTAR"]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = header_font
        cell.fill = header_fill

    # Her referansta 80 koli stok var; sevkiyatta her referans için 12, 15, 18 veya 20 koli (tam paket katı) isteyelim.
    # Böylece aynı sevkiyat Excel'ini 3-4 kez üst üste yükleyerek çoklu sevkiyat testlerini de tam paket katlarıyla yapabilirsin!
    box_counts = [12, 15, 18, 20]
    for idx, (ref_code, pack_qty) in enumerate(REFERENCES_WITH_PACK_SIZE):
        boxes_needed = box_counts[idx % len(box_counts)]
        target_qty = pack_qty * boxes_needed
        ws.append([ref_code, target_qty])

    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = 24

    return wb


def main() -> None:
    stock_wb, stock_totals = build_stock_workbook()
    ship_wb = build_shipment_workbook()

    stock_name = "Test_Stok_40_Referans_3200_Etiket.xlsx"
    ship_name = "Test_Sevkiyat_40_Referans.xlsx"

    for folder in (DESKTOP, PROJECT_ROOT):
        for wb_obj, fname in ((stock_wb, stock_name), (ship_wb, ship_name)):
            try:
                wb_obj.save(folder / fname)
            except PermissionError:
                print(f"Not: {folder / fname} şu an açık olduğu için atlandı.")

    print(f"Stok Exceli kaydedildi: {DESKTOP / stock_name} (3.200 etiket, 40 referans, toplam {sum(stock_totals.values()):,} adet)")
    print(f"Sevkiyat Exceli kaydedildi: {DESKTOP / ship_name} (40 referans, paket katlarına tam uyumlu)")


if __name__ == "__main__":
    main()
