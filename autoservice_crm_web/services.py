from __future__ import annotations

from datetime import date, datetime, timedelta
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from models import (
    Car,
    Client,
    ClientCommentHistory,
    Followup,
    FollowupHistory,
    RequestStatusHistory,
    ServiceRequest,
)

PLATE_MAP = str.maketrans({
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O",
    "Р": "P", "С": "C", "Т": "T", "У": "Y", "Х": "X",
})


def normalize_phone(phone_raw: str) -> str:
    digits = "".join(ch for ch in (phone_raw or "") if ch.isdigit())
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    elif len(digits) == 10:
        digits = "7" + digits
    elif len(digits) == 11 and digits.startswith("7"):
        pass
    return digits


def format_phone_ru(phone_raw: str) -> str:
    digits = normalize_phone(phone_raw)
    if len(digits) != 11:
        return phone_raw.strip()
    return f"8-{digits[1:4]}-{digits[4:7]}-{digits[7:9]}-{digits[9:11]}"


def normalize_name(full_name: str) -> str:
    return " ".join((full_name or "").strip().lower().split())


def normalize_plate(plate: str) -> str:
    clean = (plate or "").upper().replace(" ", "").replace("-", "")
    return clean.translate(PLATE_MAP)


def get_or_create_client(db: Session, full_name: str, phone_raw: str, email: str | None = None):
    phone_n = normalize_phone(phone_raw)
    name_n = normalize_name(full_name)

    exact = db.execute(
        select(Client).where(
            Client.phone_normalized == phone_n,
            func.lower(func.trim(Client.full_name)) == name_n,
        )
    ).scalar_one_or_none()
    if exact:
        return exact, None

    by_phone = db.execute(select(Client).where(Client.phone_normalized == phone_n)).scalar_one_or_none()
    if by_phone:
        return by_phone, f"Найден клиент по телефону: '{by_phone.full_name}'. Дубль не создан."

    client = Client(
        full_name=full_name.strip(),
        phone_raw=format_phone_ru(phone_raw),
        phone_normalized=phone_n,
        email=email,
        client_tone="Новый",
    )
    db.add(client)
    db.flush()
    return client, None


def get_or_create_car(db: Session, client_id: int, brand: str, model: str, plate: str, car_year=None, vin=None):
    brand_n = brand.strip().lower()
    model_n = model.strip().lower()
    plate_n = normalize_plate(plate)

    car = db.execute(
        select(Car).where(
            Car.client_id == client_id,
            func.lower(func.trim(Car.brand)) == brand_n,
            func.lower(func.trim(Car.model)) == model_n,
            Car.plate_number_normalized == plate_n,
        )
    ).scalar_one_or_none()
    if car:
        return car

    car = Car(
        client_id=client_id,
        brand=brand.strip(),
        model=model.strip(),
        car_year=car_year,
        plate_number=plate.strip(),
        plate_number_normalized=plate_n,
        vin=vin,
    )
    db.add(car)
    db.flush()
    return car


def create_request_with_relations(db: Session, payload: dict, created_by: str = "manager"):
    client, warning = get_or_create_client(db, payload["full_name"], payload["phone_raw"], payload.get("email"))
    car = get_or_create_car(
        db,
        client.client_id,
        payload["car_brand"],
        payload["car_model"],
        payload["car_plate"],
        payload.get("car_year"),
    )
    req = ServiceRequest(
        source_system=payload.get("source_system", "manual"),
        external_request_id=payload.get("external_request_id"),
        full_name=payload["full_name"],
        phone_raw=format_phone_ru(payload["phone_raw"]),
        phone_normalized=normalize_phone(payload["phone_raw"]),
        email=payload.get("email"),
        car_brand=payload["car_brand"],
        car_model=payload["car_model"],
        car_year=payload.get("car_year"),
        car_plate=payload["car_plate"],
        problem_description=payload["problem_description"],
        urgency=payload.get("urgency"),
        desired_visit_date=payload.get("desired_visit_date"),
        preferred_contact_slot=payload.get("preferred_contact_slot"),
        client_comment=payload.get("client_comment"),
        parts_mode=payload.get("parts_mode"),
        personal_data_consent=bool(payload.get("personal_data_consent", False)),
        request_status="Новая",
        raw_payload=payload.get("raw_payload"),
        client_id=client.client_id,
        car_id=car.car_id,
    )
    db.add(req)
    db.flush()

    db.add(RequestStatusHistory(request_id=req.request_id, old_status=None, new_status="Новая", changed_by=created_by))
    db.add(
        Followup(
            request_id=req.request_id,
            client_id=client.client_id,
            car_id=car.car_id,
            task_type="first_contact",
            title="Первичный контакт по заявке",
            description="Связаться с клиентом и уточнить детали",
            due_date=date.today(),
            task_status="Открыто",
            preferred_contact_slot=payload.get("preferred_contact_slot"),
        )
    )
    return req, warning


def change_request_status(db: Session, req: ServiceRequest, new_status: str, changed_by="manager", comment: str | None = None):
    if req.request_status == new_status:
        return False
    old = req.request_status
    req.request_status = new_status
    db.add(RequestStatusHistory(request_id=req.request_id, old_status=old, new_status=new_status, comment=comment, changed_by=changed_by))
    return True


def update_client_comment(db: Session, client: Client, new_comment: str | None, new_tone: str, new_tags: str | None, changed_by="manager"):
    old_comment = client.manager_comment
    old_tone = client.client_tone
    old_tags = client.client_tags
    changed = old_comment != new_comment or old_tone != new_tone or old_tags != new_tags
    if not changed:
        return False
    client.manager_comment = new_comment
    client.client_tone = new_tone
    client.client_tags = new_tags
    db.add(
        ClientCommentHistory(
            client_id=client.client_id,
            old_comment=old_comment,
            new_comment=new_comment,
            old_tone=old_tone,
            new_tone=new_tone,
            old_tags=old_tags,
            new_tags=new_tags,
            changed_by=changed_by,
        )
    )
    return True


def bump_followup(db: Session, followup: Followup, new_status: str, new_due: date | None = None, description: str | None = None):
    if followup.task_status == new_status and (new_due is None or followup.due_date == new_due):
        return False
    old = followup.task_status
    followup.task_status = new_status
    if new_due:
        followup.due_date = new_due
    if new_status == "Выполнено":
        followup.completed_at = datetime.utcnow()
    db.add(FollowupHistory(followup_id=followup.followup_id, old_task_status=old, new_task_status=new_status, due_date=followup.due_date, description=description))
    return True


def scenario_not_reached(db: Session, req: ServiceRequest):
    change_request_status(db, req, "В обработке", comment="Не дозвонились, перезвонить завтра")
    f = db.execute(select(Followup).where(Followup.request_id == req.request_id, Followup.task_status == "Открыто").order_by(Followup.followup_id.desc())).scalar_one_or_none()
    if not f:
        f = Followup(request_id=req.request_id, client_id=req.client_id, car_id=req.car_id, task_type="callback", title="Перезвонить", description="Не дозвонились, перезвонить завтра", due_date=date.today() + timedelta(days=1))
        db.add(f)
    else:
        bump_followup(db, f, "Открыто", date.today() + timedelta(days=1), "Не дозвонились, перезвонить завтра")
