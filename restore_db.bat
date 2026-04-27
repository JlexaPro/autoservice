@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion

set "ROOT_DIR=%~dp0"
set "APP_DIR=%ROOT_DIR%autoservice_crm_web"
set "BACKUP_DIR=%ROOT_DIR%backups"

cd /d "%APP_DIR%"
if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] .venv не найден.
  exit /b 1
)
call ".venv\Scripts\activate.bat"

set "BACKUP_FILE=%~1"
if "%BACKUP_FILE%"=="" (
  for /f "delims=" %%I in ('powershell -NoProfile -Command "Get-ChildItem '%BACKUP_DIR%' -Filter 'autoservice_backup_*.sql' | Sort-Object LastWriteTime -Descending | Select-Object -First 1 -ExpandProperty FullName"') do set "BACKUP_FILE=%%I"
)

if "%BACKUP_FILE%"=="" (
  echo [ERROR] Файл backup не найден. Укажите путь: restore_db.bat C:\path\file.sql
  exit /b 1
)

if not exist "%BACKUP_FILE%" (
  echo [ERROR] Файл backup не существует: %BACKUP_FILE%
  exit /b 1
)

for /f "delims=" %%I in ('python -c "from config import get_settings; print(get_settings().database_url.replace('+psycopg2',''))"') do set "DB_URL=%%I"

echo [INFO] Восстановление из файла: %BACKUP_FILE%
psql "%DB_URL%" -v ON_ERROR_STOP=1 -f "%BACKUP_FILE%"
if errorlevel 1 (
  echo [ERROR] Восстановление завершилось с ошибкой.
  exit /b 1
)

echo [OK] Восстановление завершено успешно.
exit /b 0
