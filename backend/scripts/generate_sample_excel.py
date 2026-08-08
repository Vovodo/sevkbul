"""Generate sample Excel files for testing."""
import sys
import os
from io import BytesIO

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from openpyxl import Workbook


def generate_samples():
    out_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'test_data')
    os.makedirs(out_dir, exist_ok=True)

    # Stok Exceli
    wb = Workbook()
    ws = wb.active
    ws.append(["SIRA", "ETİKET", "REFERANS", "MİKTAR", "EXTRA", "X98FIFO_TARIH"])
    stock_rows = [
        [1, "700024778", "6681378-HZN-1", 30, "X", "08.07.2026 10:00"],
        [2, "700024777", "6681378-HZN-1", 30, "X", "08.07.2026 14:15"],
        [3, "700024776", "6681378-HZN-1", 30, "X", "09.07.2026 13:39"],
        [4, "700024775", "6681378-HZN-1", 30, "X", "10.07.2026 08:12"],
        [5, "700024774", "6681378-HZN-1", 30, "X", "10.07.2026 09:35"],
        [6, "700024773", "6681378-HZN-1", 30, "X", "10.07.2026 14:22"],
        [7, "700024772", "6681378-HZN-1", 30, "X", "10.07.2026 17:41"],
        [8, "700024771", "6681378-HZN-1", 30, "X", "11.07.2026 10:00"],
        [9, "800001", "6035992-G", 54, "X", "01.08.2026 10:00"],
        [10, "800002", "6035992-G", 54, "X", "02.08.2026 10:00"],
        [11, "900001", "6681383-HZN-1", 30, "X", "05.08.2026 10:00"],
        [12, "900002", "6681383-HZN-1", 30, "X", "06.08.2026 10:00"],
    ]
    for row in stock_rows:
        ws.append(row)
    stock_path = os.path.join(out_dir, 'sample_stock.xlsx')
    wb.save(stock_path)

    # Sevkiyat Exceli
    wb2 = Workbook()
    ws2 = wb2.active
    ws2.append(["REFERANS", "MİKTAR"])
    ws2.append(["6681378-HZN-1", 240])
    ws2.append(["6035992-G", 108])
    ws2.append(["6681383-HZN-1", 90])
    ship_path = os.path.join(out_dir, 'sample_shipment.xlsx')
    wb2.save(ship_path)

    # Geriye uyumluluk
    wb.save(os.path.join(out_dir, 'sample_inventory.xlsx'))

    print(f"Stok Exceli: {stock_path}")
    print(f"Sevkiyat Exceli: {ship_path}")


if __name__ == "__main__":
    generate_samples()
