@echo off
chcp 65001 >nul
setlocal

set "ROOT=%~dp0.."
cd /d "%ROOT%\backend"

set "DB_MODE=%~1"
if "%DB_MODE%"=="" set "DB_MODE=postgres"

echo.
echo === SevkiyatBul Backend ===
echo.

if "%DB_MODE%"=="sqlite" (
    set "DATABASE_URL=sqlite:///./sevkiyat.db"
    echo Veritabani: SQLite ^(backend\sevkiyat.db^)
) else (
    set "DATABASE_URL=postgresql://sevkiyat:sevkiyat123@localhost:5432/sevkiyat_db"
    echo Veritabani: PostgreSQL ^(localhost:5432^)
)

echo Bagimliliklar kontrol ediliyor...
pip install -r requirements.txt -q
if errorlevel 1 (
    echo [HATA] pip install basarisiz.
    pause
    exit /b 1
)

if "%DB_MODE%"=="sqlite" (
    echo SQLite tablolari olusturuluyor...
    python -c "from app.database import Base, engine; from app.models import InventoryLabel, Shipment, ShipmentLabel, ScanLog, ShipmentTarget; Base.metadata.create_all(bind=engine)"
) else (
    echo Migration calistiriliyor...
    alembic upgrade head
    if errorlevel 1 (
        echo [HATA] Alembic migration basarisiz. PostgreSQL calisiyor mu?
        pause
        exit /b 1
    )
)

echo.
echo Eski backend surecleri kapatiliyor (port 8001)...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8001" ^| findstr "LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
)
timeout /t 2 /nobreak >nul

echo.
echo Backend baslatiliyor: http://127.0.0.1:8001
echo API Docs: http://127.0.0.1:8001/docs
echo.
uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload

pause
