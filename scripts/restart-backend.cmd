@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

set "ROOT=%~dp0.."
cd /d "%ROOT%\backend"
set "DATABASE_URL=sqlite:///./sevkiyat.db"

echo.
echo === Backend Temiz Baslatma ===
echo.

echo Port 8001 uzerindeki surecler kapatiliyor...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8001" ^| findstr "LISTENING"') do (
    echo   PID %%a sonlandiriliyor...
    taskkill /F /PID %%a >nul 2>&1
)

timeout /t 2 /nobreak >nul

echo Tablolar kontrol ediliyor...
python -c "from app.database import Base, engine; from app.models import InventoryLabel, Shipment, ShipmentLabel, ScanLog, ShipmentTarget; Base.metadata.create_all(bind=engine)"
if errorlevel 1 (
    echo [HATA] Tablo olusturma basarisiz.
    pause
    exit /b 1
)

echo.
echo Backend baslatiliyor: http://127.0.0.1:8001
echo.
python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
