@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

set "ROOT=%~dp0"
cd /d "%ROOT%"

title SevkiyatBul Baslatici

echo.
echo  ========================================
echo    SevkiyatBul - FIFO Kontrol Sistemi
echo  ========================================
echo.

:: --- Gereksinim kontrolleri ---
python --version >nul 2>&1
if errorlevel 1 (
    echo [HATA] Python bulunamadi. Python 3.12+ kurun: https://python.org
    pause
    exit /b 1
)

node --version >nul 2>&1
if errorlevel 1 (
    echo [HATA] Node.js bulunamadi. Node 20+ kurun: https://nodejs.org
    pause
    exit /b 1
)

echo [OK] Python ve Node.js bulundu.

:: --- PostgreSQL (Docker ile) ---
set "USE_SQLITE=0"
docker --version >nul 2>&1
if not errorlevel 1 (
    echo.
    echo [DB] PostgreSQL Docker ile baslatiliyor...
    docker compose up db -d
    if not errorlevel 1 (
        echo [DB] PostgreSQL hazir olana kadar bekleniyor...
        timeout /t 6 /nobreak >nul
        set "USE_SQLITE=0"
    ) else (
        echo [UYARI] Docker DB baslatilamadi, SQLite kullanilacak.
        set "USE_SQLITE=1"
    )
) else (
    echo [UYARI] Docker bulunamadi.
    echo        PostgreSQL localhost:5432 uzerinde calisiyorsa devam edilecek.
    echo        Degilse otomatik SQLite kullanilacak.
    set "USE_SQLITE=1"
)

:: --- Backend penceresi ---
if "%USE_SQLITE%"=="1" (
    start "SevkiyatBul - Backend (Port 8001)" cmd /k ""%ROOT%scripts\start-backend.cmd" sqlite"
) else (
    start "SevkiyatBul - Backend (Port 8001)" cmd /k ""%ROOT%scripts\start-backend.cmd" postgres"
)

:: --- Frontend penceresi ---
start "SevkiyatBul - Frontend (Port 5173)" cmd /k ""%ROOT%scripts\start-frontend.cmd""

:: --- Tarayici ---
echo.
echo Sunucular baslatiliyor...
echo Backend:  http://127.0.0.1:8001
echo Frontend: http://localhost:5173
echo.
echo 8 saniye sonra tarayici acilacak...
timeout /t 8 /nobreak >nul
start "" "http://localhost:5173"

echo.
echo [TAMAM] Uygulama baslatildi.
echo Kapatmak icin "Backend" ve "Frontend" pencerelerini kapatin.
echo PostgreSQL Docker kullanildiysa: scripts\stop-db.cmd ile DB durdurulabilir.
echo.
pause
