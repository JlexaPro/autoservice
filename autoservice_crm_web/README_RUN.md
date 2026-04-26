# Autoservice CRM Web (локальный MVP)

## 1) Установка
```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 2) Создание БД
```bash
createdb autoservice_crm
psql -d autoservice_crm -f ddl.sql
```

Если пользователь/пароль/хост отличаются, задайте:
```bash
export DATABASE_URL='postgresql+psycopg2://postgres:postgres@localhost:5432/autoservice_crm'
```

## 3) Запуск
```bash
python app.py
```

Открыть: http://127.0.0.1:8000

## 4) Страницы
- `/` — dashboard
- `/requests` — заявки
- `/requests/new` — ручное добавление заявки
- `/requests/{id}` — карточка заявки
- `/clients` — клиенты
- `/clients/{id}` — карточка клиента
- `/cars/{id}` — карточка авто + работы
- `/planner` — дневной планер
- `POST /service_visits` — создание визита из планера
- `PUT /service_visits/{id}` — drag&drop / resize обновление визита
- `DELETE /service_visits/{id}` — удаление визита
- `/service_visits/{id}` — карточка визита
- `/followups` — напоминания
- `/finance` — финансы и прибыль
- `/finance/export.xlsx` — выгрузка в Excel
- `/employees` — сотрудники
- `/employees/new` — добавление сотрудника
- `/promotions` — акции (MVP)
- `/settings` — настройки (MVP)
- `/settings/work-hours` — настройка рабочего времени и шага сетки
- `POST /api/incoming-request` — будущая интеграция онлайн-форм
