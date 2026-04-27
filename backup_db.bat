@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion

set "ROOT_DIR=%~dp0"
set "APP_DIR=%ROOT_DIR%autoservice_crm_web"
set "BACKUP_DIR=%ROOT_DIR%backups"
set "LOG_DIR=%APP_DIR%\logs"

if not exist "%APP_DIR%\check_app.py" (
  echo [ERROR] Не найдена папка приложения: %APP_DIR%
  exit /b 1
)

cd /d "%APP_DIR%"
if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] .venv не найден. Сначала настройте окружение.
  exit /b 1
)
call ".venv\Scripts\activate.bat"

if not exist "%BACKUP_DIR%" mkdir "%BACKUP_DIR%"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "TS=%%I"
set "BACKUP_FILE=%BACKUP_DIR%\autoservice_backup_%TS%.sql"

for /f "delims=" %%I in ('python -c "from config import get_settings; print(get_settings().database_url.replace('+psycopg2',''))"') do set "DB_URL=%%I"

if "%DB_URL%"=="" (
  echo [ERROR] DATABASE_URL не задан.
  exit /b 1
)

echo [INFO] Создание backup: %BACKUP_FILE%
pg_dump --no-owner --no-privileges --format=plain --file "%BACKUP_FILE%" "%DB_URL%"
if errorlevel 1 (
  echo [ERROR] pg_dump завершился с ошибкой.
  echo %date% %time% ERROR backup failed >> "%LOG_DIR%\backup.log"
  echo %date% %time% ERROR backup failed >> "%LOG_DIR%\app.log"
  exit /b 1
)

echo [INFO] Backup успешно создан.
echo %date% %time% INFO backup created: %BACKUP_FILE% >> "%LOG_DIR%\backup.log"
echo %date% %time% INFO backup created: %BACKUP_FILE% >> "%LOG_DIR%\app.log"

echo [INFO] Удаление старых backup (оставляем последние 14)...
powershell -NoProfile -Command "Get-ChildItem -Path '%BACKUP_DIR%' -Filter 'autoservice_backup_*.sql' | Sort-Object LastWriteTime -Descending | Select-Object -Skip 14 | Remove-Item -Force"

echo [OK] Готово.
exit /b 0
