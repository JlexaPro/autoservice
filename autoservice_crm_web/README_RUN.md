# Autoservice CRM Web — запуск для владельца автосервиса (Windows, локально)

Ниже инструкция для ежедневной работы **без Docker и без правки кода**.

## Быстрый старт (одна команда)

После скачивания проекта из корня просто запустите:

```bat
start_crm.bat
```

Скрипт сам:
- создаёт `.venv` (если нет);
- ставит зависимости;
- создаёт `.env` из шаблона (если нет);
- применяет `ddl.sql` и `migration_patch_current.sql`;
- проверяет схему;
- освобождает порт 8000;
- запускает сервер.

---

## 1) Установка Python

1. Скачайте Python 3.11+ с официального сайта: https://www.python.org/downloads/windows/
2. При установке обязательно включите галочку **Add Python to PATH**.
3. Проверьте в `cmd`:

```bat
python --version
pip --version
```

---

## 2) Подготовка проекта и виртуального окружения

Откройте `cmd` и выполните (из папки `autoservice_crm_web`):

```bat
cd C:\path\to\autoservice\autoservice_crm_web
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

---

## 3) Настройка переменных (.env)

1. Скопируйте шаблон:

```bat
copy .env.example .env
```

2. Откройте `.env` и укажите свои параметры PostgreSQL:

```env
DATABASE_URL=postgresql+psycopg2://postgres:123@localhost:5432/postgres
APP_HOST=127.0.0.1
APP_PORT=8000
APP_RELOAD=false
APP_LOG_FILE=logs/app.log
```

> Важно: приложение по умолчанию слушает только `127.0.0.1` (локальный режим).

---

## 4) Создание БД и применение схемы

Если БД ещё не подготовлена:

```bat
createdb autoservice_crm
psql -d autoservice_crm -f ddl.sql
psql -d autoservice_crm -f migration_patch_current.sql
```

Если у вас другой пользователь/пароль/хост — используйте `DATABASE_URL` из `.env`.

---

## 5) Проверка приложения перед запуском

```bat
python check_app.py
```

Скрипт проверяет:
- подключение к БД;
- количество таблиц в схеме `app`;
- ключевые таблицы;
- ключевые колонки.

Если всё хорошо — увидите `OK`.

---

## 6) Ежедневный запуск (рекомендуется)

Из корня проекта запустите:

```bat
start_crm.bat
```

Скрипт автоматически:
1. переходит в папку проекта;
2. создаёт/активирует `.venv`;
3. ставит зависимости;
4. выполняет автонастройку БД (`setup_local.py`: DDL + patch + проверка);
5. освобождает порт 8000 при необходимости;
6. запускает Uvicorn на `127.0.0.1:8000`.

Открыть в браузере:

```text
http://127.0.0.1:8000
```

---

## 7) Backup базы

Из корня проекта:

```bat
backup_db.bat
```

Что делает скрипт:
- выполняет `pg_dump`;
- сохраняет файл в папку `backups`;
- имя файла: `autoservice_backup_YYYYMMDD_HHMMSS.sql`;
- оставляет только последние 14 backup-файлов.

---

## 8) Восстановление из backup

Вариант 1: восстановить из последнего backup:

```bat
restore_db.bat
```

Вариант 2: указать конкретный файл:

```bat
restore_db.bat C:\path\to\autoservice_backup_20260427_101010.sql
```

---

## 9) Логи

Логи пишутся:
- в консоль;
- в файл `logs/app.log`.

Дополнительно backup-операции пишутся в `logs/backup.log` и `logs/app.log`.

Что логируется:
- запуск приложения;
- ошибки БД;
- создание заявки;
- создание визита;
- закрытие заказ-наряда;
- backup БД.

---

## 10) Что делать при проблемах

### Порт 8000 занят
- Используйте `start_crm.bat` — он сам завершает процесс на 8000.
- Либо вручную:

```bat
netstat -ano | findstr :8000
taskkill /PID <PID> /F
```

### Ошибка `missing column`
1. Примените патч схемы:

```bat
psql -d autoservice_crm -f migration_patch_current.sql
```

2. Проверьте:

```bat
python check_app.py
python setup_local.py
python check_schema.py
```

### Сайт не открывается
1. Убедитесь, что сервер запущен (`start_crm.bat` не закрылся с ошибкой).
2. Проверьте URL: `http://127.0.0.1:8000`.
3. Проверьте логи: `logs/app.log`.
4. Проверьте БД и структуру:

```bat
python check_app.py
```

### Ошибка подключения к PostgreSQL
- Проверьте, что служба PostgreSQL запущена.
- Проверьте `DATABASE_URL` в `.env`.
- Проверьте доступ вручную:

```bat
psql "postgresql://user:pass@localhost:5432/dbname" -c "select 1"
```

---

## 11) Безопасность локального режима

- Приложение запускается только на `127.0.0.1`.
- Для доступа извне нужна отдельная настройка сети/фаервола/реверс-прокси.
- Пароль БД хранится в `.env` (единый источник), а не размазан по коду.

---

## 12) Полезные команды

```bat
python check_app.py
python check_schema.py
python smoke_test_transactions.py
start_crm.bat
backup_db.bat
restore_db.bat
```
