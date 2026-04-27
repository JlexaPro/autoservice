@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion

echo ===============================================
echo Запуск Autoservice CRM
echo ===============================================

set "ROOT_DIR=%~dp0"
set "APP_DIR=%ROOT_DIR%autoservice_crm_web"

if not exist "%APP_DIR%\app.py" (
  echo [ERROR] Не найдена папка приложения: %APP_DIR%
  pause
  exit /b 1
)

cd /d "%APP_DIR%"

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Виртуальное окружение .venv не найдено.
  echo Создайте его: python -m venv .venv
  pause
  exit /b 1
)

call ".venv\Scripts\activate.bat"
if errorlevel 1 (
  echo [ERROR] Не удалось активировать .venv
  pause
  exit /b 1
)

echo [1/6] Проверка зависимостей...
python -c "import fastapi,uvicorn,sqlalchemy,psycopg2,openpyxl,reportlab,jinja2" 1>nul 2>nul
if errorlevel 1 (
  echo [INFO] Устанавливаю зависимости из requirements.txt...
  python -m pip install --disable-pip-version-check -r requirements.txt
  if errorlevel 1 (
    echo [ERROR] Не удалось установить зависимости.
    pause
    exit /b 1
  )
)

echo [2/6] Проверка подключения к БД и структуры app...
python check_app.py
if errorlevel 1 (
  echo [ERROR] Проверка приложения не пройдена. Исправьте ошибки выше.
  pause
  exit /b 1
)

echo [3/6] Проверка свободного порта 8000...
set "PIDS="
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":8000 .*LISTENING"') do (
  set "PIDS=!PIDS! %%P"
)

if defined PIDS (
  echo [INFO] Найдены процессы на порту 8000: !PIDS!
  for %%P in (!PIDS!) do (
    taskkill /PID %%P /F >nul 2>&1
  )
  timeout /t 1 >nul
)

echo [4/6] Запуск Uvicorn...
echo [5/6] Приложение доступно по адресу:
echo      http://127.0.0.1:8000
echo [6/6] Для остановки нажмите Ctrl+C

python -m uvicorn app:app --host 127.0.0.1 --port 8000
set "EXIT_CODE=%ERRORLEVEL%"

echo Uvicorn завершил работу с кодом %EXIT_CODE%
pause
exit /b %EXIT_CODE%
