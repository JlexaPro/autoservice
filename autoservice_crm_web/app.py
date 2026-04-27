from datetime import date, datetime, time, timedelta
from io import BytesIO
import logging
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import Date, and_, cast, func, or_, select, text
from sqlalchemy.orm import Session
from openpyxl import Workbook
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from db import get_db
from models import (
    Car,
    CarWorkHistory,
    Client,
    ClientCommentHistory,
    Employee,
    Followup,
    Payment,
    Promotion,
    RequestStatusHistory,
    AppSetting,
    ServiceBay,
    ServiceRequest,
    ServiceSlot,
    ServiceVisit,
    ServiceVisitHistory,
    SMSTemplate,
    WorkOrder,
    WorkOrderItem,
    WorkOrderPart,
    WorkOrderStatusHistory,
)
from schemas import IncomingRequestSchema
from services import (
    change_request_status,
    create_request_with_relations,
    bump_followup,
    format_phone_ru,
    normalize_phone,
    scenario_not_reached,
    update_client_comment,
)

BASE_DIR = Path(__file__).parent
app = FastAPI(title="Autoservice CRM")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.filters["phone_ru"] = format_phone_ru
logger = logging.getLogger(__name__)

DEFAULT_WORK_START = "09:00"
DEFAULT_WORK_END = "19:00"
DEFAULT_SLOT_STEP_MIN = 30


@app.on_event("startup")
def startup_migrations():
    from db import engine
    stmts = [
        "ALTER TABLE app.employees ADD COLUMN IF NOT EXISTS birth_date date",
        "ALTER TABLE app.employees ADD COLUMN IF NOT EXISTS hourly_rate numeric(12,2)",
        "ALTER TABLE app.employees ADD COLUMN IF NOT EXISTS comments text",
        "CREATE TABLE IF NOT EXISTS app.sms_templates (template_id bigserial PRIMARY KEY, template_key text UNIQUE NOT NULL, title text NOT NULL, body text NOT NULL, is_active boolean NOT NULL DEFAULT true, created_at timestamptz NOT NULL DEFAULT now())",
    ]
    with engine.begin() as conn:
        for stmt in stmts:
            conn.execute(text(stmt))
        conn.execute(text("""
            INSERT INTO app.sms_templates(template_key, title, body)
            VALUES ('to_reminder','Напомнить о ТО','{ФИО}, здравствуйте! Это автосервис. Вы были у нас на ТО {LAST_TO_DATE}. Пора повторить ТО. Даем скидку 10% при записи до {DISCOUNT_DEADLINE}.')
            ON CONFLICT (template_key) DO NOTHING
        """))
        conn.execute(text("""
            WITH c AS (
                SELECT client_id,
                       regexp_replace(coalesce(phone_raw, ''), '\\D', '', 'g') AS digits
                FROM app.clients
            ),
            n AS (
                SELECT client_id,
                       CASE
                         WHEN length(digits) = 11 AND left(digits, 1) = '8' THEN '7' || substr(digits, 2)
                         WHEN length(digits) = 10 THEN '7' || digits
                         WHEN length(digits) = 11 AND left(digits, 1) = '7' THEN digits
                         ELSE digits
                       END AS normalized
                FROM c
            )
            UPDATE app.clients cl
               SET phone_normalized = n.normalized,
                   phone_raw = CASE
                       WHEN length(n.normalized) = 11
                           THEN '8-' || substr(n.normalized, 2, 3) || '-' || substr(n.normalized, 5, 3) || '-' || substr(n.normalized, 8, 2) || '-' || substr(n.normalized, 10, 2)
                       ELSE trim(coalesce(cl.phone_raw, ''))
                   END
            FROM n
            WHERE cl.client_id = n.client_id
        """))
        conn.execute(text("""
            WITH r AS (
                SELECT request_id,
                       regexp_replace(coalesce(phone_raw, ''), '\\D', '', 'g') AS digits
                FROM app.service_requests
            ),
            n AS (
                SELECT request_id,
                       CASE
                         WHEN length(digits) = 11 AND left(digits, 1) = '8' THEN '7' || substr(digits, 2)
                         WHEN length(digits) = 10 THEN '7' || digits
                         WHEN length(digits) = 11 AND left(digits, 1) = '7' THEN digits
                         ELSE digits
                       END AS normalized
                FROM r
            )
            UPDATE app.service_requests sr
               SET phone_normalized = n.normalized,
                   phone_raw = CASE
                       WHEN length(n.normalized) = 11
                           THEN '8-' || substr(n.normalized, 2, 3) || '-' || substr(n.normalized, 5, 3) || '-' || substr(n.normalized, 8, 2) || '-' || substr(n.normalized, 10, 2)
                       ELSE trim(coalesce(sr.phone_raw, ''))
                   END
            FROM n
            WHERE sr.request_id = n.request_id
        """))


def get_setting(db: Session, key: str, default: str) -> str:
    value = db.execute(select(AppSetting.setting_value).where(AppSetting.setting_key == key)).scalar_one_or_none()
    return value or default


def get_working_grid(db: Session):
    start_s = get_setting(db, "workday_start", DEFAULT_WORK_START)
    end_s = get_setting(db, "workday_end", DEFAULT_WORK_END)
    step_s = get_setting(db, "slot_step_minutes", str(DEFAULT_SLOT_STEP_MIN))
    step_min = max(15, int(step_s))
    start_t = datetime.strptime(start_s, "%H:%M").time()
    end_t = datetime.strptime(end_s, "%H:%M").time()
    day_anchor = date.today()
    cur = datetime.combine(day_anchor, start_t)
    end_dt = datetime.combine(day_anchor, end_t)
    points = []
    while cur < end_dt:
        points.append(cur.time())
        cur += timedelta(minutes=step_min)
    return start_t, end_t, step_min, points


def none_if_empty(value):
    if value is None:
        return None
    if isinstance(value, str) and value.strip() == "":
        return None
    return value


def normalize_nullable_text(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def changed(old, new) -> bool:
    return old != new


def safe_commit(db: Session):
    db.commit()


def rollback_and_raise(db: Session, exc: Exception, public_message: str = "Внутренняя ошибка сервера"):
    db.rollback()
    if isinstance(exc, HTTPException):
        raise exc
    logger.exception("DB transaction failed: %s", exc)
    raise HTTPException(status_code=500, detail=public_message)


def normalize_dt_for_planner(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone().replace(tzinfo=None)
    return dt


def month_bounds(month_shift: int) -> tuple[date, date]:
    today = date.today()
    month_anchor = (today.replace(day=1) + timedelta(days=month_shift * 31)).replace(day=1)
    if month_anchor.month == 12:
        month_end = month_anchor.replace(year=month_anchor.year + 1, month=1, day=1) - timedelta(days=1)
    else:
        month_end = month_anchor.replace(month=month_anchor.month + 1, day=1) - timedelta(days=1)
    return month_anchor, month_end


def build_monthly_load(db: Session, month_shift: int) -> tuple[date, list[dict[str, float | int]]]:
    bays_cnt = db.scalar(select(func.count()).select_from(ServiceBay).where(ServiceBay.is_active.is_(True))) or 1
    month_anchor, month_end = month_bounds(month_shift)
    monthly_load: list[dict[str, float | int]] = []
    current = month_anchor
    while current <= month_end:
        day_visits = db.scalar(
            select(func.count()).select_from(ServiceVisit).where(cast(ServiceVisit.planned_start_at, Date) == current)
        ) or 0
        monthly_load.append({"day": current.day, "load_pct": min(100.0, (day_visits / max(1, bays_cnt * 10)) * 100)})
        current += timedelta(days=1)
    return month_anchor, monthly_load


@app.get("/")
def dashboard(request: Request, month_shift: int = 0, db: Session = Depends(get_db)):
    today = date.today()
    tomorrow = today + timedelta(days=1)
    week_ago = today - timedelta(days=7)

    new_today = db.scalar(select(func.count()).select_from(ServiceRequest).where(cast(ServiceRequest.source_created_at, Date) == today))
    overdue_followups = db.scalar(select(func.count()).select_from(Followup).where(Followup.task_status == "Открыто", Followup.due_date < today))
    booked_today = db.scalar(select(func.count()).select_from(ServiceVisit).where(cast(ServiceVisit.planned_start_at, Date) == today))
    in_work_now = db.scalar(select(func.count()).select_from(ServiceVisit).where(ServiceVisit.visit_status == "В работе"))
    done_today = db.scalar(select(func.count()).select_from(ServiceVisit).where(ServiceVisit.visit_status == "Завершён", cast(ServiceVisit.completed_at, Date) == today))
    refusals_7 = db.scalar(select(func.count()).select_from(ServiceRequest).where(ServiceRequest.request_status == "Отказ", cast(ServiceRequest.source_created_at, Date) >= week_ago))
    todays_orders = db.execute(select(WorkOrder).where(cast(WorkOrder.opened_at, Date) == today)).scalars().all()
    revenue_today = sum(float(o.total_amount or 0) for o in todays_orders)
    profit_today = sum(float(o.total_profit or 0) for o in todays_orders)
    avg_check_today = revenue_today / len(todays_orders) if todays_orders else 0
    requests_today_count = db.scalar(select(func.count()).select_from(ServiceRequest).where(cast(ServiceRequest.source_created_at, Date) == today)) or 0
    conversion_today = (booked_today / requests_today_count * 100) if requests_today_count else 0
    bays_cnt = db.scalar(select(func.count()).select_from(ServiceBay).where(ServiceBay.is_active.is_(True))) or 1
    load_pct_today = min(100.0, (booked_today / max(1, bays_cnt * 10)) * 100)
    month_anchor, monthly_load = build_monthly_load(db, month_shift)

    overdue_items = db.execute(
        select(Followup, Client).join(Client, Client.client_id == Followup.client_id).where(Followup.task_status == "Открыто", Followup.due_date < today).order_by(Followup.due_date.asc()).limit(10)
    ).all()
    visits_today = db.execute(
        select(ServiceVisit, Client, Car).join(Client, Client.client_id == ServiceVisit.client_id).join(Car, Car.car_id == ServiceVisit.car_id).where(cast(ServiceVisit.planned_start_at, Date) == today).order_by(ServiceVisit.planned_start_at.asc()).limit(20)
    ).all()

    return templates.TemplateResponse("dashboard.html", {"request": request, "cards": {
        "new_today": new_today or 0,
        "overdue_followups": overdue_followups or 0,
        "booked_today": booked_today or 0,
        "in_work_now": in_work_now or 0,
        "done_today": done_today or 0,
        "refusals_7": refusals_7 or 0,
        "revenue_today": revenue_today,
        "profit_today": profit_today,
        "avg_check_today": avg_check_today,
        "conversion_today": conversion_today,
        "load_pct_today": load_pct_today,
    }, "overdue_items": overdue_items, "visits_today": visits_today, "monthly_load": monthly_load, "month_anchor": month_anchor, "month_shift": month_shift})


@app.get("/dashboard/monthly-load.svg")
def dashboard_monthly_load_svg(month_shift: int = 0, db: Session = Depends(get_db)):
    month_anchor, monthly_load = build_monthly_load(db, month_shift)
    width = 1120
    height = 320
    left_pad = 48
    right_pad = 24
    top_pad = 24
    bottom_pad = 54
    plot_h = height - top_pad - bottom_pad
    bars = len(monthly_load) or 1
    slot = (width - left_pad - right_pad) / bars
    bar_w = max(8, slot * 0.62)
    grid = []
    for tick in (0, 25, 50, 75, 100):
        y = top_pad + plot_h - (plot_h * tick / 100)
        grid.append(f'<line x1="{left_pad}" y1="{y:.1f}" x2="{width-right_pad}" y2="{y:.1f}" stroke="#dbeafe" stroke-width="1" />')
        grid.append(f'<text x="{left_pad-8}" y="{y+4:.1f}" font-size="11" text-anchor="end" fill="#64748b">{tick}%</text>')
    rects = []
    labels = []
    for i, point in enumerate(monthly_load):
        x = left_pad + i * slot + (slot - bar_w) / 2
        bar_h = plot_h * (point["load_pct"] / 100)
        y = top_pad + plot_h - bar_h
        rects.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{max(1.0, bar_h):.1f}" rx="4" fill="url(#barGrad)"><title>День {int(point["day"])}: {point["load_pct"]:.1f}%</title></rect>'
        )
        if int(point["day"]) in {1, 5, 10, 15, 20, 25, 30, 31}:
            labels.append(f'<text x="{x + bar_w/2:.1f}" y="{height-28}" font-size="11" text-anchor="middle" fill="#475569">{int(point["day"])}</text>')
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<defs>
  <linearGradient id="bgGrad" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0%" stop-color="#f8fafc" />
    <stop offset="100%" stop-color="#eef2ff" />
  </linearGradient>
  <linearGradient id="barGrad" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0%" stop-color="#60a5fa" />
    <stop offset="100%" stop-color="#2563eb" />
  </linearGradient>
</defs>
<rect x="0" y="0" width="{width}" height="{height}" fill="url(#bgGrad)" />
<text x="{left_pad}" y="16" font-size="13" fill="#0f172a">Загрузка сервиса — {month_anchor.strftime("%m.%Y")}</text>
{''.join(grid)}
{''.join(rects)}
<line x1="{left_pad}" y1="{height-bottom_pad}" x2="{width-right_pad}" y2="{height-bottom_pad}" stroke="#94a3b8" stroke-width="1.2" />
{''.join(labels)}
</svg>"""
    return Response(content=svg, media_type="image/svg+xml")


@app.get("/requests")
def requests_page(request: Request, q: str = "", status: str = "", only_today: bool = False, only_new: bool = False, db: Session = Depends(get_db)):
    query = select(ServiceRequest).order_by(ServiceRequest.request_id.desc())
    if q:
        like = f"%{q}%"
        query = query.where(or_(ServiceRequest.full_name.ilike(like), ServiceRequest.phone_raw.ilike(like), ServiceRequest.car_plate.ilike(like), ServiceRequest.car_brand.ilike(like), ServiceRequest.car_model.ilike(like)))
    if status:
        query = query.where(ServiceRequest.request_status == status)
    if only_today:
        query = query.where(cast(ServiceRequest.source_created_at, Date) == date.today())
    if only_new:
        query = query.where(ServiceRequest.request_status == "Новая")
    rows = db.execute(query.limit(200)).scalars().all()
    return templates.TemplateResponse("requests.html", {"request": request, "rows": rows})


@app.get("/requests/new")
def request_new_form(request: Request, error: str = ""):
    return templates.TemplateResponse("request_new.html", {"request": request, "error": error})


@app.post("/requests/new")
def request_new(
    request: Request,
    full_name: str = Form(...),
    phone_raw: str = Form(...),
    car_brand: str = Form(...),
    car_model: str = Form(...),
    car_plate: str = Form(...),
    problem_description: str = Form(...),
    email: str = Form(default=""),
    car_year: int | None = Form(default=None),
    urgency: str = Form(default=""),
    desired_visit_date: date | None = Form(default=None),
    preferred_contact_slot: str = Form(default=""),
    client_comment: str = Form(default=""),
    parts_mode: str = Form(default=""),
    db: Session = Depends(get_db),
):
    payload = {
        "full_name": full_name,
        "phone_raw": format_phone_ru(phone_raw),
        "car_brand": car_brand,
        "car_model": car_model,
        "car_plate": car_plate,
        "problem_description": problem_description,
        "email": email or None,
        "car_year": car_year,
        "urgency": urgency or None,
        "desired_visit_date": desired_visit_date,
        "preferred_contact_slot": preferred_contact_slot or None,
        "client_comment": client_comment or None,
        "parts_mode": parts_mode or None,
        "source_system": "manual",
    }
    try:
        req, warning = create_request_with_relations(db, payload)
        db.flush()
        safe_commit(db)
        url = f"/requests/{req.request_id}"
        if warning:
            url += "?msg=" + warning
        return RedirectResponse(url=url, status_code=303)
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("request_new failed: %s", e)
        return RedirectResponse(url="/requests/new?error=Не удалось сохранить заявку", status_code=303)


@app.get("/requests/{request_id}")
def request_detail(request: Request, request_id: int, msg: str = "", db: Session = Depends(get_db)):
    req = db.get(ServiceRequest, request_id)
    if not req:
        raise HTTPException(404, "Заявка не найдена")
    client = db.get(Client, req.client_id) if req.client_id else None
    car = db.get(Car, req.car_id) if req.car_id else None
    history = db.execute(select(RequestStatusHistory).where(RequestStatusHistory.request_id == request_id).order_by(RequestStatusHistory.changed_at.desc())).scalars().all()
    followups = db.execute(select(Followup).where(Followup.request_id == request_id).order_by(Followup.followup_id.desc())).scalars().all()
    employees = db.execute(select(Employee).where(Employee.is_active.is_(True)).order_by(Employee.full_name)).scalars().all()
    bays = db.execute(select(ServiceBay).where(ServiceBay.is_active.is_(True)).order_by(ServiceBay.bay_name)).scalars().all()
    return templates.TemplateResponse("request_detail.html", {"request": request, "req": req, "client": client, "car": car, "history": history, "followups": followups, "employees": employees, "bays": bays, "msg": msg})


@app.post("/requests/{request_id}/status")
def request_status_action(request_id: int, action: str = Form(...), db: Session = Depends(get_db)):
    req = db.get(ServiceRequest, request_id)
    if not req:
        raise HTTPException(404, "Заявка не найдена")
    try:
        if action == "not_reached":
            scenario_not_reached(db, req)
        elif action == "booked":
            change_request_status(db, req, "Записан", comment="Записано оператором")
        elif action == "refused":
            change_request_status(db, req, "Отказ")
            for f in db.execute(select(Followup).where(Followup.request_id == request_id, Followup.task_status == "Открыто")).scalars().all():
                f.task_status = "Отменено"
        elif action == "closed":
            change_request_status(db, req, "Закрыта")
            for f in db.execute(select(Followup).where(Followup.request_id == request_id, Followup.task_status == "Открыто")).scalars().all():
                f.task_status = "Выполнено"
        else:
            raise HTTPException(400, "Неизвестное действие")
        safe_commit(db)
    except HTTPException as e:
        db.rollback()
        return RedirectResponse(f"/requests/{request_id}?msg={e.detail}", status_code=303)
    except Exception as e:
        db.rollback()
        logger.exception("request_status_action failed: %s", e)
        return RedirectResponse(f"/requests/{request_id}?msg=Ошибка изменения статуса", status_code=303)
    return RedirectResponse(f"/requests/{request_id}", status_code=303)


@app.get("/clients")
def clients_page(request: Request, q: str = "", db: Session = Depends(get_db)):
    query = select(Client).order_by(Client.client_id.desc())
    if q:
        like = f"%{q}%"
        query = query.where(or_(Client.full_name.ilike(like), Client.phone_raw.ilike(like), Client.phone_normalized.ilike(like), Client.client_tags.ilike(like)))
    clients = db.execute(query.limit(300)).scalars().all()
    return templates.TemplateResponse("clients.html", {"request": request, "clients": clients})


@app.get("/clients/new")
def client_new_form(request: Request, error: str = ""):
    return templates.TemplateResponse("client_new.html", {"request": request, "error": error})


@app.post("/clients/new")
def client_new(
    full_name: str = Form(...),
    phone_raw: str = Form(...),
    email: str = Form(default=""),
    client_tone: str = Form(default="Нейтральный"),
    client_tags: str = Form(default=""),
    manager_comment: str = Form(default=""),
    db: Session = Depends(get_db),
):
    phone_n = normalize_phone(phone_raw)
    phone_fmt = format_phone_ru(phone_raw)
    try:
        exists = db.execute(select(Client).where(Client.phone_normalized == phone_n, func.lower(func.trim(Client.full_name)) == full_name.strip().lower())).scalar_one_or_none()
        if exists:
            return RedirectResponse(f"/clients/{exists.client_id}", status_code=303)
        client = Client(
            full_name=full_name.strip(),
            phone_raw=phone_fmt,
            phone_normalized=phone_n,
            email=none_if_empty(email.strip()),
            client_tone=client_tone,
            client_tags=none_if_empty(client_tags.strip()),
            manager_comment=none_if_empty(manager_comment.strip()),
        )
        db.add(client)
        db.flush()
        safe_commit(db)
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("client_new failed: %s", e)
        return RedirectResponse("/clients/new?error=Не удалось создать клиента", status_code=303)
    return RedirectResponse(f"/clients/{client.client_id}", status_code=303)


@app.get("/clients/{client_id}")
def client_detail(request: Request, client_id: int, db: Session = Depends(get_db)):
    client = db.get(Client, client_id)
    if not client:
        raise HTTPException(404, "Клиент не найден")
    cars = db.execute(select(Car).where(Car.client_id == client_id)).scalars().all()
    reqs = db.execute(select(ServiceRequest).where(ServiceRequest.client_id == client_id).order_by(ServiceRequest.request_id.desc())).scalars().all()
    followups = db.execute(select(Followup).where(Followup.client_id == client_id).order_by(Followup.due_date.asc())).scalars().all()
    history = db.execute(select(ClientCommentHistory).where(ClientCommentHistory.client_id == client_id).order_by(ClientCommentHistory.changed_at.desc())).scalars().all()
    return templates.TemplateResponse("client_detail.html", {"request": request, "client": client, "cars": cars, "reqs": reqs, "followups": followups, "history": history})


@app.post("/clients/{client_id}/comment")
def save_client_comment(client_id: int, manager_comment: str = Form(default=""), client_tone: str = Form(default="Нейтральный"), client_tags: str = Form(default=""), db: Session = Depends(get_db)):
    client = db.get(Client, client_id)
    if not client:
        raise HTTPException(404, "Клиент не найден")
    try:
        update_client_comment(db, client, normalize_nullable_text(manager_comment), client_tone, normalize_nullable_text(client_tags))
        safe_commit(db)
    except Exception as e:
        db.rollback()
        logger.exception("save_client_comment failed: %s", e)
        return RedirectResponse(f"/clients/{client_id}?msg=Не удалось сохранить комментарий", status_code=303)
    return RedirectResponse(f"/clients/{client_id}", status_code=303)


@app.get("/cars/{car_id}")
def car_detail(request: Request, car_id: int, db: Session = Depends(get_db)):
    car = db.get(Car, car_id)
    if not car:
        raise HTTPException(404, "Авто не найдено")
    works = db.execute(select(CarWorkHistory).where(CarWorkHistory.car_id == car_id).order_by(CarWorkHistory.work_date.desc())).scalars().all()
    visits = db.execute(select(ServiceVisit).where(ServiceVisit.car_id == car_id).order_by(ServiceVisit.created_at.desc())).scalars().all()
    reqs = db.execute(select(ServiceRequest).where(ServiceRequest.car_id == car_id).order_by(ServiceRequest.request_id.desc())).scalars().all()
    employees = db.execute(select(Employee).where(Employee.is_active.is_(True)).order_by(Employee.full_name)).scalars().all()
    emp_by_number = {e.employee_number: f"{e.full_name} ({e.employee_number})" for e in employees}
    for w in works:
        if w.employee_id:
            emp = next((e for e in employees if e.employee_id == w.employee_id), None)
            w.display_employee = f"{emp.full_name} ({emp.employee_number})" if emp else (w.employee_number or "-")
        elif w.employee_number and w.employee_number in emp_by_number:
            w.display_employee = emp_by_number[w.employee_number]
        else:
            w.display_employee = w.employee_number or "-"
    return templates.TemplateResponse("car_detail.html", {"request": request, "car": car, "works": works, "visits": visits, "reqs": reqs, "employees": employees})


@app.post("/cars/{car_id}/works")
def add_car_work(car_id: int, work_date: date = Form(...), employee_id: int | None = Form(default=None), work_summary: str = Form(...), comment: str = Form(default=""), db: Session = Depends(get_db)):
    car = db.get(Car, car_id)
    if not car:
        raise HTTPException(404, "Авто не найдено")
    try:
        employee = db.get(Employee, employee_id) if employee_id else None
        db.add(CarWorkHistory(
            car_id=car_id,
            work_date=work_date,
            employee_id=employee_id,
            employee_number=f"{employee.full_name} ({employee.employee_number})" if employee else None,
            work_summary=work_summary,
            comment=normalize_nullable_text(comment),
            created_by="manager",
        ))
        safe_commit(db)
    except Exception as e:
        db.rollback()
        logger.exception("add_car_work failed: %s", e)
        return RedirectResponse(f"/cars/{car_id}?msg=Не удалось добавить запись работ", status_code=303)
    return RedirectResponse(f"/cars/{car_id}", status_code=303)


def _check_visit_overlap(db: Session, start_dt: datetime, end_dt: datetime, service_bay_id: int, employee_id: int | None, exclude_visit_id: int | None = None):
    base = select(ServiceVisit).where(
        ServiceVisit.service_bay_id == service_bay_id,
        ServiceVisit.planned_start_at < end_dt,
        ServiceVisit.planned_end_at > start_dt,
        ServiceVisit.visit_status != "Отменён",
    )
    if exclude_visit_id:
        base = base.where(ServiceVisit.visit_id != exclude_visit_id)
    if db.execute(base).scalar_one_or_none():
        raise HTTPException(400, "Этот пост уже занят в выбранное время")
    if employee_id:
        emp_q = select(ServiceVisit).where(
            ServiceVisit.assigned_employee_id == employee_id,
            ServiceVisit.planned_start_at < end_dt,
            ServiceVisit.planned_end_at > start_dt,
            ServiceVisit.visit_status != "Отменён",
        )
        if exclude_visit_id:
            emp_q = emp_q.where(ServiceVisit.visit_id != exclude_visit_id)
        if db.execute(emp_q).scalar_one_or_none():
            raise HTTPException(400, "Этот мастер уже занят в выбранное время")


def _sync_service_slot(db: Session, visit: ServiceVisit):
    slot = db.execute(select(ServiceSlot).where(ServiceSlot.visit_id == visit.visit_id)).scalar_one_or_none()
    if not slot:
        slot = ServiceSlot(visit_id=visit.visit_id, slot_status="Забронирован")
        db.add(slot)
    slot.slot_date = visit.planned_start_at.date()
    slot.start_time = visit.planned_start_at.time()
    slot.end_time = visit.planned_end_at.time()
    slot.service_bay_id = visit.service_bay_id
    slot.employee_id = visit.assigned_employee_id


def _log_service_visit_history_if_changed(
    db: Session,
    visit: ServiceVisit,
    old_status: str,
    old_start: datetime | None,
    old_end: datetime | None,
    old_employee: str | None,
    old_bay: int | None,
):
    if not any([
        changed(old_status, visit.visit_status),
        changed(old_start, visit.planned_start_at),
        changed(old_end, visit.planned_end_at),
        changed(old_employee, visit.assigned_employee_number),
        changed(old_bay, visit.service_bay_id),
    ]):
        return
    db.add(ServiceVisitHistory(
        visit_id=visit.visit_id,
        old_visit_status=old_status,
        new_visit_status=visit.visit_status,
        changed_by="manager",
        service_comment=visit.service_comment,
        planned_start_at=visit.planned_start_at,
        planned_end_at=visit.planned_end_at,
        assigned_employee_number=visit.assigned_employee_number,
        service_bay_id=visit.service_bay_id,
    ))


@app.get("/planner")
def planner(request: Request, day: date | None = None, error: str = "", grid_step: int | None = None, db: Session = Depends(get_db)):
    d = day or date.today()
    start_t, end_t, step_min, time_points = get_working_grid(db)
    if grid_step in (30, 60):
        step_min = grid_step
        day_anchor = d
        cur = datetime.combine(day_anchor, start_t)
        end_dt = datetime.combine(day_anchor, end_t)
        time_points = []
        while cur < end_dt:
            time_points.append(cur.time())
            cur += timedelta(minutes=step_min)
    bays = db.execute(select(ServiceBay).where(ServiceBay.is_active.is_(True)).order_by(ServiceBay.bay_name)).scalars().all()
    if not bays:
        try:
            db.add_all([ServiceBay(bay_name="Пост 1"), ServiceBay(bay_name="Пост 2"), ServiceBay(bay_name="Диагностика")])
            safe_commit(db)
        except Exception as e:
            db.rollback()
            logger.exception("planner init bays failed: %s", e)
            error = error or "Не удалось инициализировать посты"
        bays = db.execute(select(ServiceBay).where(ServiceBay.is_active.is_(True)).order_by(ServiceBay.bay_name)).scalars().all()
    day_start = datetime.combine(d, start_t)
    day_end = datetime.combine(d, end_t)
    visits = db.execute(
        select(ServiceVisit, Client, Car)
        .join(Client, Client.client_id == ServiceVisit.client_id)
        .join(Car, Car.car_id == ServiceVisit.car_id)
        .where(ServiceVisit.planned_start_at < day_end, ServiceVisit.planned_end_at > day_start, ServiceVisit.service_bay_id.is_not(None))
    ).all()
    visit_blocks = []
    for visit, client, car in visits:
        planned_start = normalize_dt_for_planner(visit.planned_start_at)
        planned_end = normalize_dt_for_planner(visit.planned_end_at)
        if not planned_start or not planned_end:
            continue
        top = int((planned_start - day_start).total_seconds() // 60)
        height = max(step_min, int((planned_end - planned_start).total_seconds() // 60))
        visit_blocks.append({
            "visit_id": visit.visit_id,
            "request_id": visit.request_id,
            "bay_id": visit.service_bay_id,
            "top": top,
            "height": height,
            "status": visit.visit_status,
            "start": planned_start.strftime("%H:%M"),
            "end": planned_end.strftime("%H:%M"),
            "client": client.full_name,
            "car": f"{car.brand} {car.model}",
            "plate": car.plate_number,
            "problem": visit.problem_description,
            "work_type": visit.work_type,
            "service_comment": visit.service_comment or "",
            "work_cost": float(visit.work_cost or 0),
            "master_profit": float(visit.master_profit or 0),
            "employee": visit.assigned_employee_number or "",
            "employee_id": visit.assigned_employee_id,
            "has_conflict": False,
        })
    by_bay = {}
    for v in visit_blocks:
        by_bay.setdefault(v["bay_id"], []).append(v)
    for _, bay_visits in by_bay.items():
        bay_visits.sort(key=lambda x: x["top"])
        for i, cur in enumerate(bay_visits):
            cur_start, cur_end = cur["top"], cur["top"] + cur["height"]
            for j, other in enumerate(bay_visits):
                if i == j:
                    continue
                o_start, o_end = other["top"], other["top"] + other["height"]
                if cur_start < o_end and cur_end > o_start:
                    cur["has_conflict"] = True
                    break
    employees = db.execute(select(Employee).where(Employee.is_active.is_(True))).scalars().all()
    clients = db.execute(select(Client).where(Client.is_active.is_(True)).limit(200)).scalars().all()
    cars = db.execute(select(Car).where(Car.is_active.is_(True)).limit(500)).scalars().all()
    total_minutes = int((day_end - day_start).total_seconds() // 60)
    bay_load = {}
    for bay in bays:
        used = sum(v["height"] for v in visit_blocks if v["bay_id"] == bay.service_bay_id)
        bay_load[bay.service_bay_id] = round((used / total_minutes) * 100, 1) if total_minutes else 0
    employee_load = {}
    for emp in employees:
        used = sum(v["height"] for v in visit_blocks if v.get("employee_id") == emp.employee_id)
        employee_load[emp.employee_id] = round((used / total_minutes) * 100, 1) if total_minutes else 0
    free_windows = {}
    for bay in bays:
        bay_visits = sorted([v for v in visit_blocks if v["bay_id"] == bay.service_bay_id], key=lambda x: x["top"])
        windows = []
        cursor = 0
        for visit in bay_visits:
            if visit["top"] > cursor:
                windows.append((cursor, visit["top"]))
            cursor = max(cursor, visit["top"] + visit["height"])
        if cursor < total_minutes:
            windows.append((cursor, total_minutes))
        formatted = []
        for w_start, w_end in windows:
            if w_end - w_start >= step_min:
                ws = (datetime.combine(d, start_t) + timedelta(minutes=w_start)).strftime("%H:%M")
                we = (datetime.combine(d, start_t) + timedelta(minutes=w_end)).strftime("%H:%M")
                formatted.append(f"{ws}–{we}")
        free_windows[bay.service_bay_id] = formatted
    return templates.TemplateResponse("planner.html", {
        "request": request,
        "day": d,
        "bays": bays,
        "times": [tp.strftime("%H:%M") for tp in time_points],
        "step_min": step_min,
        "visit_blocks": visit_blocks,
        "employees": employees,
        "clients": clients,
        "cars": cars,
        "start_time": start_t.strftime("%H:%M"),
        "day_minutes": total_minutes,
        "error": error,
        "bay_load": bay_load,
        "employee_load": employee_load,
        "today": date.today(),
        "prev_day": d - timedelta(days=1),
        "next_day": d + timedelta(days=1),
        "tomorrow": date.today() + timedelta(days=1),
        "free_windows": free_windows,
    })


@app.get("/planner/print")
def planner_print(request: Request, day: date | None = None, db: Session = Depends(get_db)):
    d = day or date.today()
    rows = db.execute(
        select(ServiceVisit, Client, Car, Employee, ServiceBay)
        .join(Client, Client.client_id == ServiceVisit.client_id)
        .join(Car, Car.car_id == ServiceVisit.car_id)
        .join(Employee, Employee.employee_id == ServiceVisit.assigned_employee_id, isouter=True)
        .join(ServiceBay, ServiceBay.service_bay_id == ServiceVisit.service_bay_id, isouter=True)
        .where(cast(ServiceVisit.planned_start_at, Date) == d)
        .order_by(ServiceVisit.service_bay_id, ServiceVisit.planned_start_at)
    ).all()
    return templates.TemplateResponse("planner_print.html", {"request": request, "day": d, "rows": rows})


@app.post("/service_visits/{visit_id}/action")
def service_visit_quick_action(visit_id: int, action: str = Form(...), day: date | None = Form(default=None), db: Session = Depends(get_db)):
    visit = db.get(ServiceVisit, visit_id)
    if not visit:
        return RedirectResponse(f"/planner?error=Визит не найден", status_code=303)
    try:
        old_status = visit.visit_status
        old_start = visit.planned_start_at
        old_end = visit.planned_end_at
        old_emp = visit.assigned_employee_number
        old_bay = visit.service_bay_id
        if action == "start":
            visit.visit_status = "В работе"
        elif action == "finish":
            visit.visit_status = "Завершён"
            visit.completed_at = datetime.utcnow()
        elif action == "cancel":
            visit.visit_status = "Отменён"
        else:
            return RedirectResponse(f"/planner?error=Неизвестное действие", status_code=303)
        _log_service_visit_history_if_changed(db, visit, old_status, old_start, old_end, old_emp, old_bay)
        safe_commit(db)
    except Exception as e:
        db.rollback()
        logger.exception("service_visit_quick_action failed: %s", e)
        return RedirectResponse(f"/planner?error=Не удалось изменить статус", status_code=303)
    q_day = day.isoformat() if day else date.today().isoformat()
    return RedirectResponse(f"/planner?day={q_day}", status_code=303)


@app.get("/planner/conflicts")
def planner_conflicts(day: date | None = None, db: Session = Depends(get_db)):
    d = day or date.today()
    rows = db.execute(
        select(ServiceVisit)
        .where(cast(ServiceVisit.planned_start_at, Date) == d)
        .order_by(ServiceVisit.service_bay_id, ServiceVisit.planned_start_at)
    ).scalars().all()
    conflicts = []
    for i, a in enumerate(rows):
        for j, b in enumerate(rows):
            if i >= j or a.visit_id == b.visit_id:
                continue
            if a.service_bay_id != b.service_bay_id:
                continue
            if a.planned_start_at < b.planned_end_at and a.planned_end_at > b.planned_start_at:
                conflicts.append({"visit_a": a.visit_id, "visit_b": b.visit_id, "bay_id": a.service_bay_id})
    return {"ok": True, "day": d.isoformat(), "conflicts": conflicts}


@app.get("/api/planner/auto-assign")
def planner_auto_assign(day: date, start_time: str, end_time: str, db: Session = Depends(get_db)):
    st = datetime.strptime(start_time, "%H:%M").time()
    et = datetime.strptime(end_time, "%H:%M").time()
    start_dt = datetime.combine(day, st)
    end_dt = datetime.combine(day, et)
    bays = db.execute(select(ServiceBay).where(ServiceBay.is_active.is_(True))).scalars().all()
    employees = db.execute(select(Employee).where(Employee.is_active.is_(True))).scalars().all()
    bay_scores = []
    for bay in bays:
        overlaps = db.scalar(select(func.count()).select_from(ServiceVisit).where(ServiceVisit.service_bay_id == bay.service_bay_id, ServiceVisit.planned_start_at < end_dt, ServiceVisit.planned_end_at > start_dt)) or 0
        bay_scores.append((overlaps, bay))
    emp_scores = []
    for emp in employees:
        overlaps = db.scalar(select(func.count()).select_from(ServiceVisit).where(ServiceVisit.assigned_employee_id == emp.employee_id, ServiceVisit.planned_start_at < end_dt, ServiceVisit.planned_end_at > start_dt)) or 0
        emp_scores.append((overlaps, emp))
    bay_scores.sort(key=lambda x: x[0])
    emp_scores.sort(key=lambda x: x[0])
    return {"ok": True, "bay_id": bay_scores[0][1].service_bay_id if bay_scores else None, "employee_id": emp_scores[0][1].employee_id if emp_scores else None}


@app.post("/service_visits")
def create_service_visit(
    day: date = Form(...),
    start_time: str = Form(...),
    end_time: str = Form(...),
    service_bay_id: int = Form(...),
    client_id: int = Form(...),
    car_id: str = Form(...),
    problem_description: str = Form(...),
    work_type: str = Form(...),
    employee_id: str = Form(default=""),
    request_id: str = Form(default=""),
    work_cost: str = Form(default=""),
    master_profit: str = Form(default=""),
    db: Session = Depends(get_db),
):
    car_id = str(car_id).split("|")[0].strip()
    employee_id = int(employee_id) if none_if_empty(employee_id) else None
    request_id = int(request_id) if none_if_empty(request_id) else None
    work_cost = float(work_cost) if none_if_empty(work_cost) else None
    master_profit = float(master_profit) if none_if_empty(master_profit) else None
    car_id_int = int(car_id)
    problem_description = none_if_empty(problem_description)
    work_type = none_if_empty(work_type)
    st = datetime.strptime(start_time, "%H:%M").time()
    et = datetime.strptime(end_time, "%H:%M").time()
    if et <= st:
        return RedirectResponse(f"/planner?day={day.isoformat()}&error=Время окончания должно быть позже начала", status_code=303)
    start_dt = datetime.combine(day, st)
    end_dt = datetime.combine(day, et)
    try:
        _check_visit_overlap(db, start_dt, end_dt, service_bay_id, employee_id)
        employee = db.get(Employee, employee_id) if employee_id else None
        visit = ServiceVisit(
            request_id=request_id,
            client_id=client_id,
            car_id=car_id_int,
            visit_source="request" if request_id else "manual",
            visit_status="Записан",
            work_type=work_type.strip(),
            problem_description=problem_description,
            planned_start_at=start_dt,
            planned_end_at=end_dt,
            assigned_employee_id=employee_id,
            assigned_employee_number=employee.full_name if employee else None,
            service_bay_id=service_bay_id,
            work_cost=work_cost,
            master_profit=master_profit,
        )
        db.add(visit)
        db.flush()
        _sync_service_slot(db, visit)
        _log_service_visit_history_if_changed(db, visit, "", None, None, None, None)
        if request_id:
            req = db.get(ServiceRequest, request_id)
            if req:
                change_request_status(db, req, "Записан", comment="Запись через планер")
        safe_commit(db)
    except HTTPException as e:
        db.rollback()
        return RedirectResponse(f"/planner?day={day.isoformat()}&error={e.detail}", status_code=303)
    except Exception as e:
        db.rollback()
        logger.exception("create_service_visit failed: %s", e)
        return RedirectResponse(f"/planner?day={day.isoformat()}&error=Не удалось создать визит", status_code=303)
    return RedirectResponse(f"/planner?day={day.isoformat()}", status_code=303)


@app.put("/service_visits/{visit_id}")
def update_service_visit_api(visit_id: int, payload: dict, db: Session = Depends(get_db)):
    return update_visit_common(visit_id, payload, db)


def update_visit_common(visit_id: int, payload: dict, db: Session):
    visit = db.get(ServiceVisit, visit_id)
    if not visit:
        return {"ok": False, "error": "Визит не найден"}
    try:
        day = datetime.strptime(payload["day"], "%Y-%m-%d").date()
        st = datetime.strptime(payload["start_time"], "%H:%M").time()
        et = datetime.strptime(payload["end_time"], "%H:%M").time()
    except Exception:
        return {"ok": False, "error": "Неверный формат даты/времени"}
    start_dt = datetime.combine(day, st)
    end_dt = datetime.combine(day, et)
    if end_dt <= start_dt:
        return {"ok": False, "error": "Время окончания должно быть позже начала"}
    service_bay_id = int(payload["service_bay_id"])
    employee_id = int(payload["employee_id"]) if payload.get("employee_id") else None
    try:
        old_status = visit.visit_status
        old_start = visit.planned_start_at
        old_end = visit.planned_end_at
        old_employee = visit.assigned_employee_number
        old_bay = visit.service_bay_id
        _check_visit_overlap(db, start_dt, end_dt, service_bay_id, employee_id, exclude_visit_id=visit_id)
        employee = db.get(Employee, employee_id) if employee_id else None
        visit.planned_start_at = start_dt
        visit.planned_end_at = end_dt
        visit.service_bay_id = service_bay_id
        visit.assigned_employee_id = employee_id
        visit.assigned_employee_number = employee.full_name if employee else None
        visit.client_id = int(payload["client_id"]) if payload.get("client_id") else visit.client_id
        visit.car_id = int(payload["car_id"]) if payload.get("car_id") else visit.car_id
        visit.request_id = int(payload["request_id"]) if payload.get("request_id") else visit.request_id
        visit.problem_description = none_if_empty(payload.get("problem_description")) or visit.problem_description
        visit.work_type = none_if_empty(payload.get("work_type")) or visit.work_type
        visit.service_comment = none_if_empty(payload.get("service_comment"))
        if payload.get("work_cost") is not None and str(payload.get("work_cost")).strip() != "":
            visit.work_cost = float(payload.get("work_cost"))
        if payload.get("master_profit") is not None and str(payload.get("master_profit")).strip() != "":
            visit.master_profit = float(payload.get("master_profit"))
        visit.visit_status = none_if_empty(payload.get("visit_status")) or visit.visit_status
        _sync_service_slot(db, visit)
        _log_service_visit_history_if_changed(db, visit, old_status, old_start, old_end, old_employee, old_bay)
        safe_commit(db)
        return {"ok": True, "visit": {"visit_id": visit.visit_id, "service_bay_id": visit.service_bay_id, "start_time": st.strftime("%H:%M"), "end_time": et.strftime("%H:%M")}}
    except HTTPException as e:
        db.rollback()
        return {"ok": False, "error": e.detail}
    except Exception as e:
        db.rollback()
        logger.exception("update_visit_common failed: %s", e)
        return {"ok": False, "error": "Не удалось сохранить запись"}


@app.put("/api/visits/{visit_id}/move")
def api_move_visit(visit_id: int, payload: dict, db: Session = Depends(get_db)):
    return update_visit_common(visit_id, payload, db)


@app.put("/api/visits/{visit_id}")
def api_update_visit(visit_id: int, payload: dict, db: Session = Depends(get_db)):
    return update_visit_common(visit_id, payload, db)


@app.delete("/service_visits/{visit_id}")
def delete_service_visit_api(visit_id: int, db: Session = Depends(get_db)):
    visit = db.get(ServiceVisit, visit_id)
    if not visit:
        return {"ok": False, "error": "Визит не найден"}
    try:
        slot = db.execute(select(ServiceSlot).where(ServiceSlot.visit_id == visit_id)).scalar_one_or_none()
        if slot:
            db.delete(slot)
        db.delete(visit)
        safe_commit(db)
        return {"ok": True}
    except Exception as e:
        db.rollback()
        logger.exception("delete_service_visit_api failed: %s", e)
        return {"ok": False, "error": "Не удалось удалить визит"}


@app.get("/service_visits/{visit_id}")
def service_visit_detail(request: Request, visit_id: int, db: Session = Depends(get_db)):
    row = db.execute(
        select(ServiceVisit, Client, Car, Employee, ServiceBay)
        .join(Client, Client.client_id == ServiceVisit.client_id)
        .join(Car, Car.car_id == ServiceVisit.car_id)
        .join(Employee, Employee.employee_id == ServiceVisit.assigned_employee_id, isouter=True)
        .join(ServiceBay, ServiceBay.service_bay_id == ServiceVisit.service_bay_id, isouter=True)
        .where(ServiceVisit.visit_id == visit_id)
    ).first()
    if not row:
        raise HTTPException(404, "Визит не найден")
    visit, client, car, employee, bay = row
    work_order = db.execute(
        select(WorkOrder).where(WorkOrder.visit_id == visit_id).order_by(WorkOrder.work_order_id.desc())
    ).scalars().first()
    return templates.TemplateResponse("visit_detail.html", {"request": request, "visit": visit, "client": client, "car": car, "employee": employee, "bay": bay, "work_order": work_order})


@app.get("/followups")
def followups_page(request: Request, only_open: bool = True, only_overdue: bool = False, db: Session = Depends(get_db)):
    q = select(Followup, Client, Car).join(Client, Client.client_id == Followup.client_id).join(Car, Car.car_id == Followup.car_id, isouter=True)
    if only_open:
        q = q.where(Followup.task_status == "Открыто")
    if only_overdue:
        q = q.where(Followup.due_date < date.today(), Followup.task_status == "Открыто")
    rows = db.execute(q.order_by(Followup.due_date.asc()).limit(300)).all()
    sms_templates = db.execute(select(SMSTemplate).where(SMSTemplate.is_active.is_(True)).order_by(SMSTemplate.title)).scalars().all()
    return templates.TemplateResponse("followups.html", {"request": request, "rows": rows, "today": date.today(), "sms_templates": sms_templates})


@app.get("/followups/new")
def followup_new_form(request: Request, error: str = "", db: Session = Depends(get_db)):
    clients = db.execute(select(Client).where(Client.is_active.is_(True)).order_by(Client.full_name).limit(300)).scalars().all()
    cars = db.execute(select(Car).where(Car.is_active.is_(True)).order_by(Car.car_id.desc()).limit(500)).scalars().all()
    return templates.TemplateResponse("followup_new.html", {"request": request, "clients": clients, "cars": cars, "today": date.today(), "error": error})


@app.post("/followups/new")
def followup_new(
    client_id: str = Form(...),
    car_id: str = Form(default=""),
    task_type: str = Form(...),
    due_date: date = Form(...),
    title: str = Form(...),
    description: str = Form(default=""),
    preferred_contact_slot: str = Form(default=""),
    db: Session = Depends(get_db),
):
    try:
        client_id = int(str(client_id).split("|")[0].strip())
        f = Followup(
            client_id=client_id,
            car_id=int(car_id) if none_if_empty(car_id) else None,
            task_type=task_type.strip(),
            due_date=due_date,
            title=title.strip(),
            description=none_if_empty(description.strip()),
            preferred_contact_slot=none_if_empty(preferred_contact_slot.strip()),
            task_status="Открыто",
        )
        db.add(f)
        safe_commit(db)
        return RedirectResponse("/followups", status_code=303)
    except Exception as e:
        db.rollback()
        logger.exception("followup_new failed: %s", e)
        return RedirectResponse("/followups/new?error=Не удалось создать напоминание", status_code=303)


@app.get("/followups/{followup_id}/sms-preview")
def followup_sms_preview(followup_id: int, template_key: str, db: Session = Depends(get_db)):
    f = db.get(Followup, followup_id)
    if not f:
        return {"ok": False, "error": "Напоминание не найдено"}
    template = db.execute(select(SMSTemplate).where(SMSTemplate.template_key == template_key)).scalar_one_or_none()
    if not template:
        return {"ok": False, "error": "Шаблон не найден"}
    client = db.get(Client, f.client_id)
    last_to_date = (date.today() - timedelta(days=180)).strftime("%d.%m.%Y")
    msg = template.body.replace("{ФИО}", client.full_name if client else "Клиент").replace("{LAST_TO_DATE}", last_to_date).replace("{DISCOUNT_DEADLINE}", (date.today() + timedelta(days=7)).strftime("%d.%m.%Y"))
    return {"ok": True, "phone": format_phone_ru(client.phone_raw) if client else "", "message": msg}

@app.post("/followups/{followup_id}/done")
def followup_done(followup_id: int, db: Session = Depends(get_db)):
    f = db.get(Followup, followup_id)
    if not f:
        raise HTTPException(404, "Напоминание не найдено")
    try:
        bump_followup(db, f, "Выполнено", description="Выполнено пользователем")
        safe_commit(db)
        return RedirectResponse("/followups", status_code=303)
    except Exception as e:
        db.rollback()
        logger.exception("followup_done failed: %s", e)
        return RedirectResponse("/followups?error=Не удалось завершить напоминание", status_code=303)


@app.get("/employees")
def employees_page(request: Request, db: Session = Depends(get_db)):
    rows = db.execute(select(Employee).order_by(Employee.full_name)).scalars().all()
    return templates.TemplateResponse("employees.html", {"request": request, "rows": rows})


@app.get("/employees/{employee_id}")
def employee_detail(request: Request, employee_id: int, db: Session = Depends(get_db)):
    employee = db.get(Employee, employee_id)
    if not employee:
        raise HTTPException(404, "Сотрудник не найден")
    return templates.TemplateResponse("employee_detail.html", {"request": request, "employee": employee})


@app.post("/employees/{employee_id}")
def employee_update(
    employee_id: int,
    full_name: str = Form(...),
    role: str = Form(...),
    phone: str = Form(default=""),
    birth_date: date | None = Form(default=None),
    hourly_rate: str = Form(default=""),
    specialization: str = Form(default=""),
    comments: str = Form(default=""),
    db: Session = Depends(get_db),
):
    employee = db.get(Employee, employee_id)
    if not employee:
        raise HTTPException(404, "Сотрудник не найден")
    try:
        employee.full_name = full_name.strip()
        employee.role = role.strip()
        employee.phone = normalize_nullable_text(phone)
        employee.birth_date = birth_date
        employee.hourly_rate = float(hourly_rate) if none_if_empty(hourly_rate) else None
        employee.specialization = normalize_nullable_text(specialization)
        employee.comments = normalize_nullable_text(comments)
        safe_commit(db)
    except Exception as e:
        db.rollback()
        logger.exception("employee_update failed: %s", e)
        return RedirectResponse(f"/employees/{employee_id}?error=Не удалось обновить сотрудника", status_code=303)
    return RedirectResponse(f"/employees/{employee_id}", status_code=303)


@app.post("/employees/new")
def employees_new(
    employee_number: str = Form(...),
    full_name: str = Form(...),
    role: str = Form(...),
    phone: str = Form(default=""),
    birth_date: date | None = Form(default=None),
    hourly_rate: str = Form(default=""),
    specialization: str = Form(default=""),
    comments: str = Form(default=""),
    db: Session = Depends(get_db),
):
    try:
        exists = db.execute(select(Employee).where(Employee.employee_number == employee_number.strip())).scalar_one_or_none()
        if exists:
            raise HTTPException(400, "Сотрудник с таким табельным номером уже существует")
        db.add(Employee(
            employee_number=employee_number.strip(),
            full_name=full_name.strip(),
            role=role.strip(),
            phone=normalize_nullable_text(phone),
            birth_date=birth_date,
            hourly_rate=float(hourly_rate) if none_if_empty(hourly_rate) else None,
            specialization=normalize_nullable_text(specialization),
            comments=normalize_nullable_text(comments),
        ))
        safe_commit(db)
    except HTTPException as e:
        db.rollback()
        return RedirectResponse(f"/employees?error={e.detail}", status_code=303)
    except Exception as e:
        db.rollback()
        logger.exception("employees_new failed: %s", e)
        return RedirectResponse("/employees?error=Не удалось создать сотрудника", status_code=303)
    return RedirectResponse("/employees", status_code=303)


@app.get("/promotions")
def promotions_page(request: Request, db: Session = Depends(get_db)):
    rows = db.execute(select(Promotion).order_by(Promotion.created_at.desc())).scalars().all()
    return templates.TemplateResponse("promotions.html", {"request": request, "rows": rows})


@app.get("/finance")
def finance_page(request: Request, start_date: date | None = None, end_date: date | None = None, db: Session = Depends(get_db)):
    today = date.today()
    start_date = start_date or today.replace(day=1)
    end_date = end_date or today
    closed_orders = db.execute(
        select(WorkOrder).where(
            WorkOrder.status == "Закрыт",
            cast(WorkOrder.closed_at, Date) >= start_date,
            cast(WorkOrder.closed_at, Date) <= end_date,
        )
    ).scalars().all()
    orders_by_id = {w.work_order_id: w for w in closed_orders}
    total_revenue = sum(float(w.total_amount or 0) for w in closed_orders)
    total_cost = sum(float(w.total_cost or 0) for w in closed_orders)
    gross_profit = total_revenue - total_cost
    margin_pct = (gross_profit / total_revenue * 100) if total_revenue else 0
    avg_check = total_revenue / len(closed_orders) if closed_orders else 0
    payments = db.execute(
        select(Payment).join(WorkOrder, WorkOrder.work_order_id == Payment.work_order_id).where(
            cast(Payment.payment_date, Date) >= start_date,
            cast(Payment.payment_date, Date) <= end_date,
        )
    ).scalars().all()
    paid_total = sum(float(p.amount or 0) for p in payments)
    debt_total = sum(max(0.0, float(w.total_amount or 0) - float(db.scalar(select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.work_order_id == w.work_order_id)) or 0)) for w in closed_orders)
    top_work_rows = db.execute(
        select(WorkOrderItem.work_type, func.sum(WorkOrderItem.line_total))
        .join(WorkOrder, WorkOrder.work_order_id == WorkOrderItem.work_order_id)
        .where(WorkOrder.status == "Закрыт", cast(WorkOrder.closed_at, Date) >= start_date, cast(WorkOrder.closed_at, Date) <= end_date)
        .group_by(WorkOrderItem.work_type)
        .order_by(func.sum(WorkOrderItem.line_total).desc())
        .limit(10)
    ).all()
    top_part_rows = db.execute(
        select(WorkOrderPart.part_name, func.sum(WorkOrderPart.line_profit))
        .join(WorkOrder, WorkOrder.work_order_id == WorkOrderPart.work_order_id)
        .where(WorkOrder.status == "Закрыт", cast(WorkOrder.closed_at, Date) >= start_date, cast(WorkOrder.closed_at, Date) <= end_date)
        .group_by(WorkOrderPart.part_name)
        .order_by(func.sum(WorkOrderPart.line_profit).desc())
        .limit(10)
    ).all()
    master_profit_rows = db.execute(
        select(func.coalesce(Employee.full_name, WorkOrderItem.employee_number, "Без мастера"), func.sum(WorkOrderItem.line_profit))
        .join(WorkOrder, WorkOrder.work_order_id == WorkOrderItem.work_order_id)
        .join(Employee, Employee.employee_id == WorkOrderItem.employee_id, isouter=True)
        .where(WorkOrder.status == "Закрыт", cast(WorkOrder.closed_at, Date) >= start_date, cast(WorkOrder.closed_at, Date) <= end_date)
        .group_by(func.coalesce(Employee.full_name, WorkOrderItem.employee_number, "Без мастера"))
        .order_by(func.sum(WorkOrderItem.line_profit).desc())
    ).all()
    low_profit_orders = []
    unpaid_orders = []
    for wo in closed_orders:
        if float(wo.total_profit or 0) <= 0:
            low_profit_orders.append(wo)
        paid_for_order = float(db.scalar(select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.work_order_id == wo.work_order_id)) or 0)
        if paid_for_order + 0.01 < float(wo.total_amount or 0):
            unpaid_orders.append((wo, paid_for_order, float(wo.total_amount or 0) - paid_for_order))
    return templates.TemplateResponse("finance.html", {
        "request": request,
        "start_date": start_date,
        "end_date": end_date,
        "total_revenue": total_revenue,
        "total_cost": total_cost,
        "gross_profit": gross_profit,
        "margin_pct": margin_pct,
        "avg_check": avg_check,
        "paid_total": paid_total,
        "debt_total": debt_total,
        "closed_orders_count": len(closed_orders),
        "closed_orders": closed_orders,
        "orders_by_id": orders_by_id,
        "top_works": top_work_rows,
        "top_parts": top_part_rows,
        "master_profit_rows": master_profit_rows,
        "low_profit_orders": low_profit_orders,
        "unpaid_orders": unpaid_orders,
    })


def recalc_work_order_totals(db: Session, work_order: WorkOrder):
    work_items = db.execute(select(WorkOrderItem).where(WorkOrderItem.work_order_id == work_order.work_order_id)).scalars().all()
    part_items = db.execute(select(WorkOrderPart).where(WorkOrderPart.work_order_id == work_order.work_order_id)).scalars().all()
    work_total = sum(float(i.line_total or 0) for i in work_items)
    work_cost = sum(float(i.line_cost or 0) for i in work_items)
    parts_total = sum(float(i.line_total or 0) for i in part_items)
    parts_cost = sum(float(i.line_cost or 0) for i in part_items)
    work_order.work_total = work_total
    work_order.parts_total = parts_total
    work_order.parts_cost_total = parts_cost
    work_order.total_amount = work_total + parts_total
    work_order.total_cost = work_cost + parts_cost
    work_order.total_profit = work_order.total_amount - work_order.total_cost


@app.get("/work-orders")
def work_orders_page(request: Request, db: Session = Depends(get_db)):
    rows = db.execute(
        select(WorkOrder, Client, Car)
        .join(Client, Client.client_id == WorkOrder.client_id)
        .join(Car, Car.car_id == WorkOrder.car_id)
        .order_by(WorkOrder.opened_at.desc())
    ).all()
    return templates.TemplateResponse("work_orders.html", {"request": request, "rows": rows})


@app.get("/work-orders/new")
def work_order_new_form(request: Request, error: str = "", db: Session = Depends(get_db)):
    clients = db.execute(select(Client).where(Client.is_active.is_(True)).order_by(Client.full_name).limit(300)).scalars().all()
    cars = db.execute(select(Car).where(Car.is_active.is_(True)).order_by(Car.car_id.desc()).limit(500)).scalars().all()
    employees = db.execute(select(Employee).where(Employee.is_active.is_(True))).scalars().all()
    bays = db.execute(select(ServiceBay).where(ServiceBay.is_active.is_(True))).scalars().all()
    return templates.TemplateResponse("work_order_new.html", {"request": request, "clients": clients, "cars": cars, "employees": employees, "bays": bays, "error": error})


@app.post("/visits/{visit_id}/work-order")
def create_work_order_from_visit(visit_id: int, db: Session = Depends(get_db)):
    visit = db.get(ServiceVisit, visit_id)
    if not visit:
        return RedirectResponse("/planner?error=Визит не найден", status_code=303)
    existing_open = db.execute(
        select(WorkOrder).where(WorkOrder.visit_id == visit_id, WorkOrder.status != "Закрыт")
    ).scalars().first()
    if existing_open:
        return RedirectResponse(f"/work-orders/{existing_open.work_order_id}", status_code=303)
    existing_any = db.execute(select(WorkOrder).where(WorkOrder.visit_id == visit_id)).scalars().first()
    if existing_any and existing_any.status != "Закрыт":
        return RedirectResponse(f"/work-orders/{existing_any.work_order_id}", status_code=303)
    try:
        order_number = f"WO-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        wo = WorkOrder(
            order_number=order_number,
            request_id=visit.request_id,
            visit_id=visit.visit_id,
            client_id=visit.client_id,
            car_id=visit.car_id,
            assigned_employee_id=visit.assigned_employee_id,
            service_bay_id=visit.service_bay_id,
            status="Открыт",
            created_by="manager",
            comment="Создан из визита",
        )
        db.add(wo)
        db.flush()
        db.add(WorkOrderStatusHistory(work_order_id=wo.work_order_id, old_status=None, new_status="Открыт", changed_by="manager"))
        safe_commit(db)
        return RedirectResponse(f"/work-orders/{wo.work_order_id}", status_code=303)
    except Exception as e:
        db.rollback()
        logger.exception("create_work_order_from_visit failed: %s", e)
        return RedirectResponse(f"/service_visits/{visit_id}?error=Не удалось создать заказ-наряд", status_code=303)


@app.post("/work-orders/new")
def work_order_new(
    client_id: int = Form(...),
    car_id: int = Form(...),
    assigned_employee_id: int | None = Form(default=None),
    service_bay_id: int | None = Form(default=None),
    comment: str = Form(default=""),
    db: Session = Depends(get_db),
):
    try:
        order_number = f"WO-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        wo = WorkOrder(
            order_number=order_number,
            client_id=client_id,
            car_id=car_id,
            assigned_employee_id=none_if_empty(assigned_employee_id),
            service_bay_id=none_if_empty(service_bay_id),
            comment=none_if_empty(comment),
            status="Открыт",
            created_by="manager",
        )
        db.add(wo)
        db.flush()
        db.add(WorkOrderStatusHistory(work_order_id=wo.work_order_id, old_status=None, new_status="Открыт", changed_by="manager"))
        safe_commit(db)
    except Exception as e:
        db.rollback()
        logger.exception("work_order_new failed: %s", e)
        return RedirectResponse("/work-orders/new?error=Не удалось создать заказ-наряд", status_code=303)
    return RedirectResponse(f"/work-orders/{wo.work_order_id}", status_code=303)


@app.get("/work-orders/{work_order_id}")
def work_order_detail(request: Request, work_order_id: int, db: Session = Depends(get_db)):
    wo = db.get(WorkOrder, work_order_id)
    if not wo:
        raise HTTPException(404, "Заказ-наряд не найден")
    client = db.get(Client, wo.client_id)
    car = db.get(Car, wo.car_id)
    items = db.execute(select(WorkOrderItem).where(WorkOrderItem.work_order_id == work_order_id)).scalars().all()
    parts = db.execute(select(WorkOrderPart).where(WorkOrderPart.work_order_id == work_order_id)).scalars().all()
    payments = db.execute(select(Payment).where(Payment.work_order_id == work_order_id).order_by(Payment.payment_date.desc())).scalars().all()
    history = db.execute(select(WorkOrderStatusHistory).where(WorkOrderStatusHistory.work_order_id == work_order_id).order_by(WorkOrderStatusHistory.changed_at.desc())).scalars().all()
    employees = db.execute(select(Employee).where(Employee.is_active.is_(True))).scalars().all()
    margin_pct = (float(wo.total_profit or 0) / float(wo.total_amount) * 100) if float(wo.total_amount or 0) > 0 else 0
    paid_total = sum(float(p.amount or 0) for p in payments)
    due_total = float(wo.total_amount or 0) - paid_total
    return templates.TemplateResponse("work_order_detail.html", {
        "request": request,
        "wo": wo,
        "client": client,
        "car": car,
        "items": items,
        "parts": parts,
        "payments": payments,
        "paid_total": paid_total,
        "due_total": due_total,
        "is_unpaid": due_total > 0.01,
        "margin_pct": margin_pct,
        "history": history,
        "employees": employees,
    })


@app.get("/work-orders/{work_order_id}/export.pdf")
def work_order_pdf(work_order_id: int, db: Session = Depends(get_db)):
    wo = db.get(WorkOrder, work_order_id)
    if not wo:
        raise HTTPException(404, "Заказ-наряд не найден")
    client = db.get(Client, wo.client_id)
    car = db.get(Car, wo.car_id)
    items = db.execute(select(WorkOrderItem).where(WorkOrderItem.work_order_id == work_order_id)).scalars().all()
    parts = db.execute(select(WorkOrderPart).where(WorkOrderPart.work_order_id == work_order_id)).scalars().all()
    font_name = "Helvetica"
    for path in [
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/Library/Fonts/Arial.ttf",
    ]:
        try:
            pdfmetrics.registerFont(TTFont("UnicodeFont", path))
            font_name = "UnicodeFont"
            break
        except Exception:
            continue
    buff = BytesIO()
    pdf = canvas.Canvas(buff, pagesize=A4)
    y = 800
    pdf.setFont(font_name, 13)
    pdf.drawString(40, y, f"Заказ-наряд № {wo.order_number}")
    y -= 20
    pdf.setFont(font_name, 10)
    pdf.drawString(40, y, f"Дата: {wo.opened_at}")
    y -= 15
    pdf.drawString(40, y, f"Клиент: {client.full_name if client else ''}")
    y -= 15
    pdf.drawString(40, y, f"Авто: {car.brand if car else ''} {car.model if car else ''} {car.plate_number if car else ''}")
    y -= 20
    pdf.setFont(font_name, 11)
    pdf.drawString(40, y, "Работы")
    y -= 15
    pdf.setFont(font_name, 10)
    for i in items:
        pdf.drawString(45, y, f"{i.work_type} | {i.qty} x {i.unit_price} = {i.line_total}")
        y -= 13
    y -= 8
    pdf.setFont(font_name, 11)
    pdf.drawString(40, y, "Запчасти")
    y -= 15
    pdf.setFont(font_name, 10)
    for p in parts:
        pdf.drawString(45, y, f"{p.part_name} | {p.qty} x {p.sale_price} = {p.line_total}")
        y -= 13
    y -= 15
    pdf.setFont(font_name, 11)
    pdf.drawString(40, y, f"Итого к оплате: {wo.total_amount}")
    pdf.showPage()
    pdf.save()
    buff.seek(0)
    return StreamingResponse(buff, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename=\"work_order_{wo.order_number}.pdf\"'})


@app.post("/work-orders/{work_order_id}/items")
def add_work_order_item(
    work_order_id: int,
    work_type: str = Form(...),
    description: str = Form(default=""),
    qty: float = Form(1),
    unit_price: float = Form(0),
    unit_cost: float = Form(0),
    comment: str = Form(default=""),
    employee_id: str = Form(default=""),
    employee_number: str = Form(default=""),
    db: Session = Depends(get_db),
):
    wo = db.get(WorkOrder, work_order_id)
    if not wo:
        raise HTTPException(404, "Заказ-наряд не найден")
    try:
        employee_id_int = int(employee_id) if none_if_empty(employee_id) else None
        employee = db.get(Employee, employee_id_int) if employee_id_int else None
        line_total = qty * unit_price
        line_cost = qty * unit_cost
        db.add(WorkOrderItem(
            work_order_id=work_order_id,
            work_type=work_type,
            description=none_if_empty(description),
            comment=none_if_empty(comment),
            employee_id=employee_id_int,
            employee_number=(employee.full_name if employee else normalize_nullable_text(employee_number)),
            qty=qty,
            unit_price=unit_price,
            unit_cost=unit_cost,
            line_total=line_total,
            line_cost=line_cost,
            line_profit=line_total - line_cost,
        ))
        recalc_work_order_totals(db, wo)
        safe_commit(db)
    except Exception as e:
        db.rollback()
        logger.exception("add_work_order_item failed: %s", e)
        return RedirectResponse(f"/work-orders/{work_order_id}?error=Не удалось добавить работу", status_code=303)
    return RedirectResponse(f"/work-orders/{work_order_id}", status_code=303)


@app.post("/work-orders/{work_order_id}/parts")
def add_work_order_part(work_order_id: int, part_name: str = Form(...), part_number: str = Form(default=""), part_brand: str = Form(default=""), comment: str = Form(default=""), qty: float = Form(1), sale_price: float = Form(0), cost_price: float = Form(0), db: Session = Depends(get_db)):
    wo = db.get(WorkOrder, work_order_id)
    if not wo:
        raise HTTPException(404, "Заказ-наряд не найден")
    try:
        line_total = qty * sale_price
        line_cost = qty * cost_price
        db.add(WorkOrderPart(
            work_order_id=work_order_id,
            part_name=part_name,
            part_number=normalize_nullable_text(part_number),
            part_brand=normalize_nullable_text(part_brand),
            comment=normalize_nullable_text(comment),
            qty=qty,
            sale_price=sale_price,
            cost_price=cost_price,
            line_total=line_total,
            line_cost=line_cost,
            line_profit=line_total - line_cost,
        ))
        recalc_work_order_totals(db, wo)
        safe_commit(db)
    except Exception as e:
        db.rollback()
        logger.exception("add_work_order_part failed: %s", e)
        return RedirectResponse(f"/work-orders/{work_order_id}?error=Не удалось добавить запчасть", status_code=303)
    return RedirectResponse(f"/work-orders/{work_order_id}", status_code=303)


@app.post("/work-orders/{work_order_id}/payments")
def add_work_order_payment(
    work_order_id: int,
    amount: float = Form(...),
    payment_method: str = Form(default="Наличные"),
    comment: str = Form(default=""),
    db: Session = Depends(get_db),
):
    wo = db.get(WorkOrder, work_order_id)
    if not wo:
        return RedirectResponse(f"/work-orders/{work_order_id}?error=Заказ-наряд не найден", status_code=303)
    try:
        recalc_work_order_totals(db, wo)
        if amount <= 0:
            return RedirectResponse(f"/work-orders/{work_order_id}?error=Сумма оплаты должна быть больше 0", status_code=303)
        paid_total = db.scalar(select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.work_order_id == work_order_id)) or 0
        if float(paid_total) + amount > float(wo.total_amount or 0):
            return RedirectResponse(f"/work-orders/{work_order_id}?error=Оплата превышает сумму заказ-наряда", status_code=303)
        methods = {"Наличные", "Карта", "Перевод", "Смешанная оплата"}
        if payment_method not in methods:
            payment_method = "Наличные"
        db.add(Payment(work_order_id=work_order_id, amount=amount, payment_method=payment_method, comment=normalize_nullable_text(comment), created_by="manager"))
        safe_commit(db)
    except Exception as e:
        db.rollback()
        logger.exception("add_work_order_payment failed: %s", e)
        return RedirectResponse(f"/work-orders/{work_order_id}?error=Не удалось добавить оплату", status_code=303)
    return RedirectResponse(f"/work-orders/{work_order_id}", status_code=303)


@app.post("/work-orders/{work_order_id}/status")
def update_work_order_status(
    work_order_id: int,
    status: str = Form(...),
    payment_amount: str = Form(default=""),
    payment_method: str = Form(default="Наличные"),
    payment_comment: str = Form(default=""),
    db: Session = Depends(get_db),
):
    wo = db.get(WorkOrder, work_order_id)
    if not wo:
        raise HTTPException(404, "Заказ-наряд не найден")
    if wo.status == "Закрыт":
        return RedirectResponse(f"/work-orders/{work_order_id}?error=Заказ-наряд уже закрыт", status_code=303)
    if wo.status == status and status != "Закрыт":
        return RedirectResponse(f"/work-orders/{work_order_id}", status_code=303)
    try:
        recalc_work_order_totals(db, wo)
        items_cnt = db.scalar(select(func.count()).select_from(WorkOrderItem).where(WorkOrderItem.work_order_id == work_order_id)) or 0
        parts_cnt = db.scalar(select(func.count()).select_from(WorkOrderPart).where(WorkOrderPart.work_order_id == work_order_id)) or 0
        if status == "Закрыт" and (items_cnt + parts_cnt) == 0:
            return RedirectResponse(f"/work-orders/{work_order_id}?error=Нельзя закрыть пустой заказ-наряд", status_code=303)
        if status == "Закрыт" and float(wo.total_amount or 0) <= 0:
            return RedirectResponse(f"/work-orders/{work_order_id}?error=Нельзя закрыть заказ-наряд без итоговой суммы", status_code=303)
        old = wo.status
        wo.status = status
        if status == "Закрыт":
            allowed_methods = {"Наличные", "Карта", "Перевод", "Смешанная оплата"}
            payment_method = payment_method if payment_method in allowed_methods else "Наличные"
            paid_before = db.scalar(select(func.coalesce(func.sum(Payment.amount), 0)).where(Payment.work_order_id == work_order_id)) or 0
            amount = float(payment_amount) if none_if_empty(payment_amount) else 0.0
            if float(paid_before) == 0 and amount <= 0:
                return RedirectResponse(f"/work-orders/{work_order_id}?error=Перед закрытием добавьте оплату", status_code=303)
            if amount > 0:
                if float(paid_before) + amount > float(wo.total_amount or 0):
                    return RedirectResponse(f"/work-orders/{work_order_id}?error=Оплата больше суммы заказ-наряда", status_code=303)
                db.add(Payment(
                    work_order_id=work_order_id,
                    amount=amount,
                    payment_method=payment_method,
                    comment=normalize_nullable_text(payment_comment),
                    created_by="manager",
                ))
            wo.closed_at = datetime.utcnow()
            if wo.visit_id:
                visit = db.get(ServiceVisit, wo.visit_id)
                if visit:
                    old_visit_status = visit.visit_status
                    old_start = visit.planned_start_at
                    old_end = visit.planned_end_at
                    old_emp = visit.assigned_employee_number
                    old_bay = visit.service_bay_id
                    visit.visit_status = "Завершён"
                    visit.completed_at = datetime.utcnow()
                    _log_service_visit_history_if_changed(db, visit, old_visit_status, old_start, old_end, old_emp, old_bay)
                    if visit.request_id:
                        req = db.get(ServiceRequest, visit.request_id)
                        if req:
                            change_request_status(db, req, "Закрыта", comment=f"Заказ-наряд {wo.order_number} закрыт")
            db.add(Followup(
                request_id=wo.request_id,
                client_id=wo.client_id,
                car_id=wo.car_id,
                task_type="service_reminder",
                title="Напомнить о повторном обслуживании",
                description=f"Follow-up после закрытия заказ-наряда {wo.order_number}",
                due_date=(date.today() + timedelta(days=90)),
                task_status="Открыто",
            ))
        db.add(WorkOrderStatusHistory(work_order_id=work_order_id, old_status=old, new_status=status, changed_by="manager"))
        safe_commit(db)
    except Exception as e:
        db.rollback()
        logger.exception("update_work_order_status failed: %s", e)
        return RedirectResponse(f"/work-orders/{work_order_id}?error=Не удалось изменить статус", status_code=303)
    return RedirectResponse(f"/work-orders/{work_order_id}", status_code=303)


@app.get("/finance/export.xlsx")
def finance_export(start_date: date | None = None, end_date: date | None = None, db: Session = Depends(get_db)):
    today = date.today()
    start_date = start_date or today.replace(day=1)
    end_date = end_date or today
    visits = db.execute(
        select(ServiceVisit, Employee, Client, Car, ServiceBay)
        .join(Employee, Employee.employee_id == ServiceVisit.assigned_employee_id, isouter=True)
        .join(Client, Client.client_id == ServiceVisit.client_id)
        .join(Car, Car.car_id == ServiceVisit.car_id)
        .join(ServiceBay, ServiceBay.service_bay_id == ServiceVisit.service_bay_id, isouter=True)
        .where(cast(ServiceVisit.planned_start_at, Date) >= start_date, cast(ServiceVisit.planned_start_at, Date) <= end_date)
        .order_by(ServiceVisit.planned_start_at.asc())
    ).all()
    wb = Workbook()
    ws = wb.active
    ws.title = "Финансы"
    ws.append(["Дата", "Клиент", "Авто", "Пост", "Мастер", "Вид работы", "Проблема", "Стоимость", "Прибыль мастера", "Прибыль сервиса"])
    for visit, employee, client, car, bay in visits:
        cost = float(visit.work_cost or 0)
        mp = float(visit.master_profit or 0)
        ws.append([
            visit.planned_start_at.strftime("%Y-%m-%d %H:%M") if visit.planned_start_at else "",
            client.full_name,
            f"{car.brand} {car.model} {car.plate_number}",
            bay.bay_name if bay else "",
            employee.full_name if employee else "",
            visit.work_type,
            visit.problem_description,
            cost,
            mp,
            cost - mp,
        ])
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    filename = f"finance_{start_date}_{end_date}.xlsx"
    return StreamingResponse(output, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f'attachment; filename=\"{filename}\"'})


@app.get("/settings")
def settings_page(request: Request, db: Session = Depends(get_db)):
    workday_start = get_setting(db, "workday_start", DEFAULT_WORK_START)
    workday_end = get_setting(db, "workday_end", DEFAULT_WORK_END)
    slot_step_minutes = get_setting(db, "slot_step_minutes", str(DEFAULT_SLOT_STEP_MIN))
    return templates.TemplateResponse("settings.html", {"request": request, "workday_start": workday_start, "workday_end": workday_end, "slot_step_minutes": slot_step_minutes})


@app.post("/settings/work-hours")
def update_work_hours(
    workday_start: str = Form(...),
    workday_end: str = Form(...),
    slot_step_minutes: int = Form(...),
    db: Session = Depends(get_db),
):
    try:
        for key, value, desc in [
            ("workday_start", workday_start, "Начало рабочего дня"),
            ("workday_end", workday_end, "Конец рабочего дня"),
            ("slot_step_minutes", str(slot_step_minutes), "Шаг сетки планера в минутах"),
        ]:
            row = db.get(AppSetting, key)
            if not row:
                row = AppSetting(setting_key=key, setting_value=value, description=desc)
                db.add(row)
            else:
                row.setting_value = value
        safe_commit(db)
    except Exception as e:
        db.rollback()
        logger.exception("update_work_hours failed: %s", e)
        return RedirectResponse("/settings?error=Не удалось сохранить настройки", status_code=303)
    return RedirectResponse("/settings", status_code=303)


@app.post("/api/incoming-request")
def api_incoming_request(payload: IncomingRequestSchema, db: Session = Depends(get_db)):
    data = payload.model_dump()
    data["phone_raw"] = data.pop("phone")
    data["phone_raw"] = format_phone_ru(data["phone_raw"])
    data["personal_data_consent"] = True
    data["source_system"] = data.get("source_system") or "web_form"
    try:
        req, warning = create_request_with_relations(db, data, created_by="api")
        db.flush()
        safe_commit(db)
        return {"ok": True, "request_id": req.request_id, "warning": warning, "phone_normalized": normalize_phone(data["phone_raw"])}
    except HTTPException as e:
        db.rollback()
        return {"ok": False, "error": e.detail}
    except Exception as e:
        db.rollback()
        logger.exception("api_incoming_request failed: %s", e)
        return {"ok": False, "error": "Не удалось создать заявку"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
