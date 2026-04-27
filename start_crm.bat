@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

echo ================================================
echo Autoservice CRM - безопасный запуск
echo ================================================

set "ROOT_DIR=%~dp0"
set "APP_DIR=%ROOT_DIR%autoservice_crm_web"

echo Root: %ROOT_DIR%
echo App : %APP_DIR%
echo.

if not exist "%APP_DIR%\app.py" goto :err_no_app

cd /d "%APP_DIR%"
if errorlevel 1 goto :err_cd

if not exist ".env" (
  if exist ".env.example" (
    copy /Y ".env.example" ".env" >nul
    echo [1/6] Создан .env из .env.example
  ) else (
    goto :err_no_env_example
  )
) else (
  echo [1/6] .env уже существует
)

if not exist ".venv\Scripts\python.exe" (
  echo [2/6] Создание виртуального окружения...
  python -m venv .venv
  if errorlevel 1 goto :err_venv
) else (
  echo [2/6] Активация виртуального окружения...
)

call ".venv\Scripts\activate.bat"
if errorlevel 1 goto :err_activate

echo [3/6] Установка зависимостей...
python -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto :err_requirements

echo [4/6] Проверка и автоподготовка БД...
python setup_local.py
if errorlevel 1 goto :err_setup

echo [5/6] Освобождение порта 8000 (если занят)...
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":8000 .*LISTENING"') do taskkill /PID %%P /F >nul 2>&1

echo [6/6] Запуск сервера...
echo Откройте в браузере: http://127.0.0.1:8000
echo Для остановки нажмите Ctrl+C
python -m uvicorn app:app --host 127.0.0.1 --port 8000 --no-use-colors
if errorlevel 1 goto :err_uvicorn

goto :ok

:err_no_app
echo [ERROR] Не найдена папка приложения: %APP_DIR%
goto :pause

:err_cd
echo [ERROR] Не удалось перейти в папку приложения.
goto :pause

:err_no_env_example
echo [ERROR] Не найден файл .env.example
goto :pause

:err_venv
echo [ERROR] Не удалось создать .venv. Проверьте Python в PATH.
goto :pause

:err_activate
echo [ERROR] Не удалось активировать .venv
goto :pause

:err_requirements
echo [ERROR] Не удалось установить зависимости.
goto :pause

:err_setup
echo [ERROR] setup_local.py завершился с ошибкой.
goto :pause

:err_uvicorn
echo [ERROR] Uvicorn завершился с ошибкой.
goto :pause

:ok
echo.
echo Готово.
set "EXIT_CODE=0"
goto :pause

:pause
echo Для продолжения нажмите любую клавишу . . .
pause >nul
if not defined EXIT_CODE set "EXIT_CODE=1"
exit /b %EXIT_CODE%
