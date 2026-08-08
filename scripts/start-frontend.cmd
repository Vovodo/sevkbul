@echo off
chcp 65001 >nul
setlocal

set "ROOT=%~dp0.."
cd /d "%ROOT%\frontend"

echo.
echo === SevkiyatBul Frontend ===
echo.

if not exist "node_modules\" (
    echo npm paketleri yukleniyor...
    call npm install
    if errorlevel 1 (
        echo [HATA] npm install basarisiz.
        pause
        exit /b 1
    )
)

echo Frontend baslatiliyor: http://localhost:5173
echo.
call npm run dev

pause
