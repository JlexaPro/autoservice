from datetime import date, datetime, time, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import and_, cast, func, or_, select
from sqlalchemy.orm import Session

from db import get_db
from models import (
    Car,
    CarWorkHistory,
    Client,
    ClientCommentHistory,
    Employee,
    Followup,
    Promotion,
    RequestStatusHistory,
    AppSetting,
    ServiceBay,
    ServiceRequest,
    ServiceSlot,
    ServiceVisit,
)
from schemas import IncomingRequestSchema
from services import (
    change_request_status,
    create_request_with_relations,
    normalize_phone,
    scenario_not_reached,
    update_client_comment,
)

BASE_DIR = Path(__file__).parent
app = FastAPI(title="Autoservice CRM")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

DEFAULT_WORK_START = "09:00"
DEFAULT_WORK_END = "19:00"
DEFAULT_SLOT_STEP_MIN = 30


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


@app.get("/")
def dashboard(request: Request, db: Session = Depends(get_db)):
    today = date.today()
    tomorrow = today + timedelta(days=1)
    week_ago = today - timedelta(days=7)

    new_today = db.scalar(select(func.count()).select_from(ServiceRequest).where(cast(ServiceRequest.source_created_at, date) == today))
    overdue_followups = db.scalar(select(func.count()).select_from(Followup).where(Followup.task_status == "Открыто", Followup.due_date < today))
    booked_today = db.scalar(select(func.count()).select_from(ServiceVisit).where(cast(ServiceVisit.planned_start_at, date) == today))
    in_work_now = db.scalar(select(func.count()).select_from(ServiceVisit).where(ServiceVisit.visit_status == "В работе"))
    done_today = db.scalar(select(func.count()).select_from(ServiceVisit).where(ServiceVisit.visit_status == "Завершён", cast(ServiceVisit.completed_at, date) == today))
    refusals_7 = db.scalar(select(func.count()).select_from(ServiceRequest).where(ServiceRequest.request_status == "Отказ", cast(ServiceRequest.source_created_at, date) >= week_ago))

    overdue_items = db.execute(
        select(Followup, Client).join(Client, Client.client_id == Followup.client_id).where(Followup.task_status == "Открыто", Followup.due_date < today).order_by(Followup.due_date.asc()).limit(10)
    ).all()
    visits_today = db.execute(
        select(ServiceVisit, Client, Car).join(Client, Client.client_id == ServiceVisit.client_id).join(Car, Car.car_id == ServiceVisit.car_id).where(cast(ServiceVisit.planned_start_at, date) == today).order_by(ServiceVisit.planned_start_at.asc()).limit(20)
    ).all()

    return templates.TemplateResponse("dashboard.html", {"request": request, "cards": {
        "new_today": new_today or 0,
        "overdue_followups": overdue_followups or 0,
        "booked_today": booked_today or 0,
        "in_work_now": in_work_now or 0,
        "done_today": done_today or 0,
        "refusals_7": refusals_7 or 0,
    }, "overdue_items": overdue_items, "visits_today": visits_today})


@app.get("/requests")
def requests_page(request: Request, q: str = "", status: str = "", only_today: bool = False, only_new: bool = False, db: Session = Depends(get_db)):
    query = select(ServiceRequest).order_by(ServiceRequest.request_id.desc())
    if q:
        like = f"%{q}%"
        query = query.where(or_(ServiceRequest.full_name.ilike(like), ServiceRequest.phone_raw.ilike(like), ServiceRequest.car_plate.ilike(like), ServiceRequest.car_brand.ilike(like), ServiceRequest.car_model.ilike(like)))
    if status:
        query = query.where(ServiceRequest.request_status == status)
    if only_today:
        query = query.where(cast(ServiceRequest.source_created_at, date) == date.today())
    if only_new:
        query = query.where(ServiceRequest.request_status == "Новая")
    rows = db.execute(query.limit(200)).scalars().all()
    return templates.TemplateResponse("requests.html", {"request": request, "rows": rows})


@app.get("/requests/new")
def request_new_form(request: Request):
    return templates.TemplateResponse("request_new.html", {"request": request})


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
        "phone_raw": phone_raw,
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
        with db.begin():
            req, warning = create_request_with_relations(db, payload)
        url = f"/requests/{req.request_id}"
        if warning:
            url += "?msg=" + warning
        return RedirectResponse(url=url, status_code=303)
    except Exception as e:
        db.rollback()
        return templates.TemplateResponse("request_new.html", {"request": request, "error": f"Ошибка сохранения: {e}"})


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
    with db.begin():
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
    return RedirectResponse(f"/requests/{request_id}", status_code=303)


@app.get("/clients")
def clients_page(request: Request, q: str = "", db: Session = Depends(get_db)):
    query = select(Client).order_by(Client.client_id.desc())
    if q:
        like = f"%{q}%"
        query = query.where(or_(Client.full_name.ilike(like), Client.phone_raw.ilike(like), Client.phone_normalized.ilike(like), Client.client_tags.ilike(like)))
    clients = db.execute(query.limit(300)).scalars().all()
    return templates.TemplateResponse("clients.html", {"request": request, "clients": clients})


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
    with db.begin():
        update_client_comment(db, client, manager_comment or None, client_tone, client_tags or None)
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
    return templates.TemplateResponse("car_detail.html", {"request": request, "car": car, "works": works, "visits": visits, "reqs": reqs, "employees": employees})


@app.post("/cars/{car_id}/works")
def add_car_work(car_id: int, work_date: date = Form(...), employee_id: int | None = Form(default=None), work_summary: str = Form(...), comment: str = Form(default=""), db: Session = Depends(get_db)):
    car = db.get(Car, car_id)
    if not car:
        raise HTTPException(404, "Авто не найдено")
    with db.begin():
        employee = db.get(Employee, employee_id) if employee_id else None
        db.add(CarWorkHistory(
            car_id=car_id,
            work_date=work_date,
            employee_id=employee_id,
            employee_number=employee.full_name if employee else None,
            work_summary=work_summary,
            comment=comment or None,
            created_by="manager",
        ))
    return RedirectResponse(f"/cars/{car_id}", status_code=303)


@app.get("/planner")
def planner(request: Request, day: date | None = None, db: Session = Depends(get_db)):
    d = day or date.today()
    _, _, _, time_points = get_working_grid(db)
    bays = db.execute(select(ServiceBay).where(ServiceBay.is_active.is_(True)).order_by(ServiceBay.bay_name)).scalars().all()
    if not bays:
        with db.begin():
            db.add_all([ServiceBay(bay_name="Пост 1"), ServiceBay(bay_name="Пост 2"), ServiceBay(bay_name="Диагностика")])
        bays = db.execute(select(ServiceBay).where(ServiceBay.is_active.is_(True)).order_by(ServiceBay.bay_name)).scalars().all()
    slots = db.execute(select(ServiceSlot, ServiceVisit, Client, Car).join(ServiceVisit, ServiceVisit.visit_id == ServiceSlot.visit_id).join(Client, Client.client_id == ServiceVisit.client_id).join(Car, Car.car_id == ServiceVisit.car_id).where(ServiceSlot.slot_date == d)).all()
    grid = {b.service_bay_id: {tp.strftime("%H:%M"): None for tp in time_points} for b in bays}
    for s, v, c, car in slots:
        if s.service_bay_id not in grid:
            continue
        for tp in time_points:
            if s.start_time <= tp < s.end_time:
                grid[s.service_bay_id][tp.strftime("%H:%M")] = {
                    "slot": s,
                    "visit": v,
                    "client": c,
                    "car": car,
                    "is_start": tp == s.start_time,
                }
    employees = db.execute(select(Employee).where(Employee.is_active.is_(True))).scalars().all()
    clients = db.execute(select(Client).where(Client.is_active.is_(True)).limit(200)).scalars().all()
    cars = db.execute(select(Car).where(Car.is_active.is_(True)).limit(500)).scalars().all()
    return templates.TemplateResponse("planner.html", {"request": request, "day": d, "bays": bays, "grid": grid, "times": [tp.strftime("%H:%M") for tp in time_points], "employees": employees, "clients": clients, "cars": cars})


@app.post("/planner/book")
def planner_book(
    day: date = Form(...),
    start_time: str = Form(...),
    end_time: str = Form(...),
    service_bay_id: int = Form(...),
    client_id: int = Form(...),
    car_id: int = Form(...),
    problem_description: str = Form(...),
    work_type: str = Form(...),
    employee_id: int | None = Form(default=None),
    request_id: int | None = Form(default=None),
    work_cost: float | None = Form(default=None),
    master_profit: float | None = Form(default=None),
    db: Session = Depends(get_db),
):
    st = datetime.strptime(start_time, "%H:%M").time()
    et = datetime.strptime(end_time, "%H:%M").time()
    if et <= st:
        raise HTTPException(400, "Время окончания должно быть позже начала")

    overlap_bay = db.execute(select(ServiceSlot).where(
        ServiceSlot.slot_date == day,
        ServiceSlot.service_bay_id == service_bay_id,
        ServiceSlot.start_time < et,
        ServiceSlot.end_time > st,
        ServiceSlot.slot_status.in_(["Забронирован", "Занят"])
    )).scalars().first()
    if overlap_bay:
        raise HTTPException(400, "Этот пост уже занят в выбранное время")

    if employee_id:
        overlap_emp = db.execute(select(ServiceSlot).where(
            ServiceSlot.slot_date == day,
            ServiceSlot.employee_id == employee_id,
            ServiceSlot.start_time < et,
            ServiceSlot.end_time > st,
            ServiceSlot.slot_status.in_(["Забронирован", "Занят"])
        )).scalars().first()
        if overlap_emp:
            raise HTTPException(400, "Этот мастер уже занят в выбранное время")

    with db.begin():
        employee = db.get(Employee, employee_id) if employee_id else None
        visit = ServiceVisit(
            request_id=request_id,
            client_id=client_id,
            car_id=car_id,
            visit_source="request" if request_id else "manual",
            visit_status="Записан",
            work_type=work_type.strip(),
            problem_description=problem_description,
            planned_start_at=datetime.combine(day, st),
            planned_end_at=datetime.combine(day, et),
            assigned_employee_id=employee_id,
            assigned_employee_number=employee.full_name if employee else None,
            service_bay_id=service_bay_id,
            work_cost=work_cost,
            master_profit=master_profit,
        )
        db.add(visit)
        db.flush()
        db.add(ServiceSlot(slot_date=day, start_time=st, end_time=et, service_bay_id=service_bay_id, employee_id=employee_id, slot_status="Забронирован", visit_id=visit.visit_id))
        if request_id:
            req = db.get(ServiceRequest, request_id)
            if req:
                change_request_status(db, req, "Записан", comment="Запись через планер")
    return RedirectResponse(f"/planner?day={day.isoformat()}", status_code=303)


@app.get("/followups")
def followups_page(request: Request, only_open: bool = True, only_overdue: bool = False, db: Session = Depends(get_db)):
    q = select(Followup, Client, Car).join(Client, Client.client_id == Followup.client_id).join(Car, Car.car_id == Followup.car_id, isouter=True)
    if only_open:
        q = q.where(Followup.task_status == "Открыто")
    if only_overdue:
        q = q.where(Followup.due_date < date.today(), Followup.task_status == "Открыто")
    rows = db.execute(q.order_by(Followup.due_date.asc()).limit(300)).all()
    return templates.TemplateResponse("followups.html", {"request": request, "rows": rows, "today": date.today()})


@app.post("/followups/{followup_id}/done")
def followup_done(followup_id: int, db: Session = Depends(get_db)):
    f = db.get(Followup, followup_id)
    if not f:
        raise HTTPException(404, "Напоминание не найдено")
    with db.begin():
        f.task_status = "Выполнено"
        f.completed_at = datetime.utcnow()
    return RedirectResponse("/followups", status_code=303)


@app.get("/employees")
def employees_page(request: Request, db: Session = Depends(get_db)):
    rows = db.execute(select(Employee).order_by(Employee.full_name)).scalars().all()
    return templates.TemplateResponse("employees.html", {"request": request, "rows": rows})


@app.post("/employees/new")
def employees_new(
    employee_number: str = Form(...),
    full_name: str = Form(...),
    role: str = Form(...),
    phone: str = Form(default=""),
    specialization: str = Form(default=""),
    db: Session = Depends(get_db),
):
    with db.begin():
        exists = db.execute(select(Employee).where(Employee.employee_number == employee_number.strip())).scalar_one_or_none()
        if exists:
            raise HTTPException(400, "Сотрудник с таким табельным номером уже существует")
        db.add(Employee(
            employee_number=employee_number.strip(),
            full_name=full_name.strip(),
            role=role.strip(),
            phone=phone.strip() or None,
            specialization=specialization.strip() or None,
        ))
    return RedirectResponse("/employees", status_code=303)


@app.get("/promotions")
def promotions_page(request: Request, db: Session = Depends(get_db)):
    rows = db.execute(select(Promotion).order_by(Promotion.created_at.desc())).scalars().all()
    return templates.TemplateResponse("promotions.html", {"request": request, "rows": rows})


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
    with db.begin():
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
    return RedirectResponse("/settings", status_code=303)


@app.post("/api/incoming-request")
def api_incoming_request(payload: IncomingRequestSchema, db: Session = Depends(get_db)):
    data = payload.model_dump()
    data["phone_raw"] = data.pop("phone")
    data["personal_data_consent"] = True
    data["source_system"] = data.get("source_system") or "web_form"
    with db.begin():
        req, warning = create_request_with_relations(db, data, created_by="api")
    return {"ok": True, "request_id": req.request_id, "warning": warning, "phone_normalized": normalize_phone(data["phone_raw"])}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
