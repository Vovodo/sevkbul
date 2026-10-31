"""1000 satırlık test stok Exceli. Kolonlar stok import algoritmasıyla aynıdır."""
from datetime import datetime, timedelta
from pathlib import Path

from openpyxl import Workbook

OUT = Path(r"C:\Users\egepa\OneDrive\Desktop\stok_test_1000.xlsx")

REFERENCES = [
    "6681401-HZN-1",
    "6681402-HZN-1",
    "6681403-HZE-1",
    "6681404-HZE-1",
    "6681405-HYC-1",
    "6681406-HYC-1",
    "6036001-G",
    "6036002-G",
    "6681407-HZN-1",
    "6681408-HZE-1",
    "6695301-HZE-1",
    "6695302-HZE-1",
    "6763301-HZE-1",
    "6681409-HZN-1",
    "6681410-HYC-1",
    "6036003-G",
    "6681411-HZN-1",
    "6681412-HZE-1",
    "6681413-HYC-1",
    "6036004-G",
]
QUANTITIES = [15, 30, 30, 45, 30]
HOURS = [(8, 15), (9, 30), (10, 45), (13, 20), (16, 5)]


def main() -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Stok"
    ws.append(["ETİKET", "REFERANS", "MİKTAR", "X98FIFO_TARIH"])

    start = datetime(2026, 6, 1)
    for i in range(1000):
        label = str(710000001 + i)
        reference = REFERENCES[i % len(REFERENCES)]
        quantity = QUANTITIES[i % len(QUANTITIES)]
        day = start + timedelta(days=(i // len(REFERENCES)) % 20)
        hour, minute = HOURS[(i // len(REFERENCES)) % len(HOURS)]
        fifo = day.replace(hour=hour, minute=minute).strftime("%d.%m.%Y %H:%M")
        ws.append([label, reference, quantity, fifo])

    wb.save(OUT)
    print(OUT)
    print(ws.max_row - 1)


if __name__ == "__main__":
    main()
