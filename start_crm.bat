@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion

echo ===============================================
echo Автонастройка и запуск Autoservice CRM
echo ===============================================

set "ROOT_DIR=%~dp0"
set "APP_DIR=%ROOT_DIR%autoservice_crm_web"

if not exist "%APP_DIR%\app.py" (
  echo [ERROR] Не найдена папка приложения: %APP_DIR%
  pause
  exit /b 1
)

cd /d "%APP_DIR%"

if not exist ".env" (
  if exist ".env.example" (
    copy /Y ".env.example" ".env" >nul
    echo [INFO] Создан .env из .env.example
  ) else (
    echo [ERROR] Не найден .env.example
    goto :fail
  )
)

if not exist ".venv\Scripts\python.exe" (
  echo [1/8] Создание виртуального окружения...
  python -m venv .venv
  if errorlevel 1 (
    echo [ERROR] Не удалось создать .venv. Проверьте установку Python.
    goto :fail
  )
)

call ".venv\Scripts\activate.bat"
if errorlevel 1 (
  echo [ERROR] Не удалось активировать .venv
  goto :fail
)

echo [2/8] Установка зависимостей...
python -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
  echo [ERROR] Не удалось установить зависимости.
  goto :fail
)

echo [3/8] Проверка библиотек...
python -c "import fastapi,uvicorn,sqlalchemy,psycopg2,openpyxl,reportlab,jinja2" 1>nul 2>nul
if errorlevel 1 (
  echo [ERROR] После установки зависимостей не удалось импортировать библиотеки.
  goto :fail
)

echo [4/8] Автоподготовка БД (DDL + patch + проверка)...
python setup_local.py
if errorlevel 1 (
  echo [ERROR] Автоподготовка БД не пройдена.
  goto :fail
)

echo [5/8] Проверка свободного порта 8000...
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

echo [6/8] Запуск Uvicorn...
echo [7/8] Приложение доступно по адресу:
echo      http://127.0.0.1:8000
echo [8/8] Для остановки нажмите Ctrl+C

python -m uvicorn app:app --host 127.0.0.1 --port 8000
set "EXIT_CODE=%ERRORLEVEL%"

echo Uvicorn завершил работу с кодом %EXIT_CODE%
pause
exit /b %EXIT_CODE%

:fail
echo.
echo Нажмите любую клавишу, чтобы закрыть окно...
pause >nul
exit /b 1
