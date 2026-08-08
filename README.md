# sevkbul - Akıllı FIFO Sevkiyat & Barkod Kontrol Sistemi

Endüstriyel depolar için tasarlanmış yüksek performanslı **FIFO (First-In, First-Out)** dinamik kontenjan tahsis ve barkod/QR okutma kontrol uygulaması.

## 🚀 Özellikler

- **Dinamik FIFO Tarih Grubu Kontenjan Tahsisi:** Stoktaki aynı FIFO tarihine sahip aday etiketlerden kontenjan dolana kadar esnek kabul, dolduğu an otomatik engelleme.
- **Akıllı Barkod/QR Normalizasyonu:** Okuyucudan gelen ön ekli barkodları (`s700024541`, `S700024541`, `P700024541` vb.) otomatik ayıklayıp veritabanı etiketiyle anında eşleştirme.
- **Çift Excel Desteği:** 
  - Stok Exceli yükleme (Otomatik kolon tespiti ve eşleme)
  - Sevkiyat Exceli yükleme (`REFERANS` - `MİKTAR` eşlemesi)
- **Web Audio API Ses Motoru:** 7 farklı başarılı melodi (Siber Melodi, Kristal Zil, Majestik Arpej vb.) ve 7 farklı başarısız ikaz sesi (Endüstriyel Siren, Siber Red, Derin Darbe vb.).
- **Kompakt Modern Dashboard:** Yüksek bilgi yoğunluğuna sahip canlı takip ekranı.

## 🛠️ Teknolojiler

- **Backend:** Python 3.12 + FastAPI + SQLAlchemy
- **Frontend:** React 18 + Vite + TypeScript + Web Audio API
- **Veritabanı:** SQLite / PostgreSQL

## 💻 Hızlı Başlangıç

### Windows Kolay Başlatıcı

```cmd
start.cmd
```

- **Frontend:** http://localhost:5173
- **Backend API:** http://localhost:8001
- **API Docs:** http://localhost:8001/docs

### Manuel Kurulum

**Backend:**
```bash
cd backend
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8001
```

**Frontend:**
```bash
cd frontend
npm install
npm run dev
```

## 🧪 Test Komutu

```bash
cd backend
python -m pytest -v
```

---

Özel depo ve lojistik ihtiyaçları için geliştirilmiştir.
