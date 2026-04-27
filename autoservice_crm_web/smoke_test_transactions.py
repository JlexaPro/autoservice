#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select

from db import SessionLocal
from models import Car, Client, Payment, ServiceVisit, WorkOrder, WorkOrderItem
from services import create_request_with_relations, format_phone_ru, normalize_phone


def main() -> int:
    db = SessionLocal()
    stamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    print(f"[smoke] starting transaction smoke run {stamp}")
    try:
        # 1) create client
        client = Client(
            full_name=f"Smoke Client {stamp}",
            phone_raw=format_phone_ru("89991112233"),
            phone_normalized=normalize_phone("89991112233"),
            is_active=True,
        )
        db.add(client)
        db.flush()
        print(f"[smoke] client_id={client.client_id}")

        # 2) create car
        car = Car(
            client_id=client.client_id,
            brand="Lada",
            model="Vesta",
            plate_number=f"T{stamp[-3:]}AA77",
            plate_number_normalized=f"T{stamp[-3:]}AA77",
            is_active=True,
        )
        db.add(car)
        db.flush()
        print(f"[smoke] car_id={car.car_id}")

        # 3) create request (service layer)
        payload = {
            "full_name": client.full_name,
            "phone_raw": client.phone_raw,
            "car_brand": car.brand,
            "car_model": car.model,
            "car_plate": car.plate_number,
            "problem_description": "Smoke transaction check",
            "source_system": "smoke",
        }
        req, warning = create_request_with_relations(db, payload, created_by="smoke")
        db.flush()
        print(f"[smoke] request_id={req.request_id}, warning={warning}")

        # 4) create visit
        start_dt = datetime.utcnow() + timedelta(hours=1)
        end_dt = start_dt + timedelta(hours=1)
        visit = ServiceVisit(
            request_id=req.request_id,
            client_id=req.client_id,
            car_id=req.car_id,
            visit_source="smoke",
            visit_status="Записан",
            work_type="Диагностика",
            problem_description="Smoke visit",
            planned_start_at=start_dt,
            planned_end_at=end_dt,
        )
        db.add(visit)
        db.flush()
        print(f"[smoke] visit_id={visit.visit_id}")

        # 5) move visit
        visit.planned_start_at = start_dt + timedelta(minutes=30)
        visit.planned_end_at = end_dt + timedelta(minutes=30)
        db.flush()
        print("[smoke] visit moved")

        # 6) create work order
        wo = WorkOrder(
            order_number=f"SMOKE-{stamp}",
            request_id=req.request_id,
            visit_id=visit.visit_id,
            client_id=req.client_id,
            car_id=req.car_id,
            status="Создан",
        )
        db.add(wo)
        db.flush()
        print(f"[smoke] work_order_id={wo.work_order_id}")

        # 7) add work item
        item = WorkOrderItem(
            work_order_id=wo.work_order_id,
            work_type="Диагностика",
            qty=1,
            unit_price=1000,
            unit_cost=400,
            line_total=1000,
            line_cost=400,
            line_profit=600,
        )
        db.add(item)
        db.flush()
        print("[smoke] work item added")

        # 8) close work order
        wo.status = "Закрыт"
        wo.closed_at = datetime.utcnow()
        db.add(Payment(work_order_id=wo.work_order_id, amount=1000, payment_method="Наличные", created_by="smoke"))
        db.commit()
        print("[smoke] work order closed")

        # 9) verify persisted
        assert db.execute(select(Client).where(Client.client_id == client.client_id)).scalar_one_or_none() is not None
        assert db.execute(select(Car).where(Car.car_id == car.car_id)).scalar_one_or_none() is not None
        assert db.execute(select(ServiceVisit).where(ServiceVisit.visit_id == visit.visit_id)).scalar_one_or_none() is not None
        assert db.execute(select(WorkOrder).where(WorkOrder.work_order_id == wo.work_order_id)).scalar_one_or_none() is not None
        print("[smoke] verification passed")
        return 0
    except Exception as e:
        db.rollback()
        print(f"[smoke] FAILED: {e}")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
