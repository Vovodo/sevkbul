"""10 referanslı test sevkiyat Exceli. Kolonlar sevkiyat import algoritmasıyla aynıdır."""
from pathlib import Path

from openpyxl import Workbook

OUT = Path(r"C:\Users\egepa\OneDrive\Desktop\sevkiyat_test_10.xlsx")

# Etiket adedi 15 veya 30 olan referanslar. 120 her ikisine de tam bölünür
# (15 x 8, 30 x 4). 45'lik referanslar alınmadı; 120 onlara tam bölünmez.
ROWS = [
    ("6681401-HZN-1", 120),
    ("6681406-HYC-1", 120),
    ("6695301-HZE-1", 120),
    ("6036003-G", 120),
    ("6681402-HZN-1", 120),
    ("6681403-HZE-1", 120),
    ("6681405-HYC-1", 120),
    ("6036001-G", 120),
    ("6036002-G", 120),
    ("6681408-HZE-1", 120),
]


def main() -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Sevkiyat"
    ws.append(["REFERANS", "MİKTAR"])
    for reference, quantity in ROWS:
        ws.append([reference, quantity])
    wb.save(OUT)
    print(OUT)
    print(len(ROWS))


if __name__ == "__main__":
    main()
