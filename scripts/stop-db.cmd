@echo off
chcp 65001 >nul
cd /d "%~dp0.."

echo PostgreSQL durduruluyor...
docker compose stop db
echo Tamam.
