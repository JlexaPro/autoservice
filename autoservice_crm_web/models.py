from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Integer, BigInteger, Numeric, Text, Time, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from db import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = {"schema": "app"}
    user_id = Column(BigInteger, primary_key=True)
    username = Column(Text, unique=True, nullable=False)
    password_hash = Column(Text)
    full_name = Column(Text, nullable=False)
    role = Column(Text, nullable=False, default="manager")
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Employee(Base):
    __tablename__ = "employees"
    __table_args__ = {"schema": "app"}
    employee_id = Column(BigInteger, primary_key=True)
    employee_number = Column(Text, nullable=False, unique=True)
    full_name = Column(Text, nullable=False)
    role = Column(Text, nullable=False)
    phone = Column(Text)
    birth_date = Column(Date)
    hourly_rate = Column(Numeric(12, 2))
    comments = Column(Text)
    specialization = Column(Text)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Client(Base):
    __tablename__ = "clients"
    __table_args__ = {"schema": "app"}
    client_id = Column(BigInteger, primary_key=True)
    full_name = Column(Text, nullable=False)
    phone_raw = Column(Text, nullable=False)
    phone_normalized = Column(Text, nullable=False)
    email = Column(Text)
    client_tone = Column(Text, nullable=False, default="Нейтральный")
    client_tags = Column(Text)
    manager_comment = Column(Text)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    cars = relationship("Car", back_populates="client")


class ClientCommentHistory(Base):
    __tablename__ = "client_comment_history"
    __table_args__ = {"schema": "app"}
    history_id = Column(BigInteger, primary_key=True)
    client_id = Column(BigInteger, ForeignKey("app.clients.client_id"), nullable=False)
    old_comment = Column(Text)
    new_comment = Column(Text)
    old_tone = Column(Text)
    new_tone = Column(Text)
    old_tags = Column(Text)
    new_tags = Column(Text)
    changed_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    changed_by = Column(Text)


class Car(Base):
    __tablename__ = "cars"
    __table_args__ = {"schema": "app"}
    car_id = Column(BigInteger, primary_key=True)
    client_id = Column(BigInteger, ForeignKey("app.clients.client_id"), nullable=False)
    brand = Column(Text, nullable=False)
    model = Column(Text, nullable=False)
    car_year = Column(Integer)
    plate_number = Column(Text, nullable=False)
    plate_number_normalized = Column(Text)
    vin = Column(Text)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    client = relationship("Client", back_populates="cars")


class CarWorkHistory(Base):
    __tablename__ = "car_work_history"
    __table_args__ = {"schema": "app"}
    history_id = Column(BigInteger, primary_key=True)
    car_id = Column(BigInteger, ForeignKey("app.cars.car_id"), nullable=False)
    work_date = Column(Date, nullable=False)
    employee_id = Column(BigInteger, ForeignKey("app.employees.employee_id"))
    employee_number = Column(Text)
    work_summary = Column(Text, nullable=False)
    comment = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_by = Column(Text)


class ServiceRequest(Base):
    __tablename__ = "service_requests"
    __table_args__ = {"schema": "app"}
    request_id = Column(BigInteger, primary_key=True)
    external_request_id = Column(Text, unique=True)
    source_system = Column(Text, nullable=False, default="manual")
    source_file_name = Column(Text)
    source_created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    import_dttm = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    client_id = Column(BigInteger, ForeignKey("app.clients.client_id"))
    car_id = Column(BigInteger, ForeignKey("app.cars.car_id"))
    full_name = Column(Text, nullable=False)
    phone_raw = Column(Text, nullable=False)
    phone_normalized = Column(Text, nullable=False)
    email = Column(Text)
    car_brand = Column(Text, nullable=False)
    car_model = Column(Text, nullable=False)
    car_year = Column(Integer)
    car_plate = Column(Text, nullable=False)
    parts_mode = Column(Text)
    problem_description = Column(Text, nullable=False)
    urgency = Column(Text)
    desired_visit_date = Column(Date)
    preferred_contact_slot = Column(Text)
    client_comment = Column(Text)
    personal_data_consent = Column(Boolean, nullable=False, default=False)
    request_status = Column(Text, nullable=False, default="Новая")
    raw_payload = Column(JSONB)


class RequestStatusHistory(Base):
    __tablename__ = "request_status_history"
    __table_args__ = {"schema": "app"}
    history_id = Column(BigInteger, primary_key=True)
    request_id = Column(BigInteger, ForeignKey("app.service_requests.request_id"), nullable=False)
    old_status = Column(Text)
    new_status = Column(Text, nullable=False)
    changed_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    changed_by = Column(Text)
    comment = Column(Text)


class ServiceBay(Base):
    __tablename__ = "service_bays"
    __table_args__ = {"schema": "app"}
    service_bay_id = Column(BigInteger, primary_key=True)
    bay_name = Column(Text, nullable=False)
    bay_type = Column(Text)
    is_active = Column(Boolean, nullable=False, default=True)
    comment = Column(Text)


class AppSetting(Base):
    __tablename__ = "app_settings"
    __table_args__ = {"schema": "app"}
    setting_key = Column(Text, primary_key=True)
    setting_value = Column(Text, nullable=False)
    description = Column(Text)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ServiceVisit(Base):
    __tablename__ = "service_visits"
    __table_args__ = {"schema": "app"}
    visit_id = Column(BigInteger, primary_key=True)
    request_id = Column(BigInteger, ForeignKey("app.service_requests.request_id"))
    client_id = Column(BigInteger, ForeignKey("app.clients.client_id"), nullable=False)
    car_id = Column(BigInteger, ForeignKey("app.cars.car_id"), nullable=False)
    visit_source = Column(Text, nullable=False, default="request")
    visit_status = Column(Text, nullable=False, default="Создан")
    work_type = Column(Text, nullable=False, default="Общее")
    problem_description = Column(Text, nullable=False)
    parts_mode = Column(Text)
    urgency = Column(Text)
    desired_visit_date = Column(Date)
    preferred_contact_slot = Column(Text)
    client_comment = Column(Text)
    service_comment = Column(Text)
    work_cost = Column(Numeric(12, 2))
    master_profit = Column(Numeric(12, 2))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    planned_start_at = Column(DateTime(timezone=True))
    planned_end_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    assigned_employee_id = Column(BigInteger, ForeignKey("app.employees.employee_id"))
    assigned_employee_number = Column(Text)
    service_bay_id = Column(BigInteger, ForeignKey("app.service_bays.service_bay_id"))


class ServiceVisitHistory(Base):
    __tablename__ = "service_visit_history"
    __table_args__ = {"schema": "app"}
    history_id = Column(BigInteger, primary_key=True)
    visit_id = Column(BigInteger, ForeignKey("app.service_visits.visit_id"), nullable=False)
    old_visit_status = Column(Text)
    new_visit_status = Column(Text, nullable=False)
    changed_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    changed_by = Column(Text)
    service_comment = Column(Text)
    planned_start_at = Column(DateTime(timezone=True))
    planned_end_at = Column(DateTime(timezone=True))
    assigned_employee_number = Column(Text)
    service_bay_id = Column(BigInteger)


class Followup(Base):
    __tablename__ = "followups"
    __table_args__ = {"schema": "app"}
    followup_id = Column(BigInteger, primary_key=True)
    request_id = Column(BigInteger, ForeignKey("app.service_requests.request_id"))
    client_id = Column(BigInteger, ForeignKey("app.clients.client_id"), nullable=False)
    car_id = Column(BigInteger, ForeignKey("app.cars.car_id"))
    visit_id = Column(BigInteger, ForeignKey("app.service_visits.visit_id"))
    task_type = Column(Text, nullable=False)
    task_status = Column(Text, nullable=False, default="Открыто")
    due_date = Column(Date, nullable=False)
    preferred_contact_slot = Column(Text)
    title = Column(Text, nullable=False)
    description = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    completed_at = Column(DateTime(timezone=True))


class FollowupHistory(Base):
    __tablename__ = "followup_history"
    __table_args__ = {"schema": "app"}
    history_id = Column(BigInteger, primary_key=True)
    followup_id = Column(BigInteger, ForeignKey("app.followups.followup_id"), nullable=False)
    old_task_status = Column(Text)
    new_task_status = Column(Text, nullable=False)
    changed_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    changed_by = Column(Text)
    description = Column(Text)
    due_date = Column(Date)


class ServiceSlot(Base):
    __tablename__ = "service_slots"
    __table_args__ = {"schema": "app"}
    slot_id = Column(BigInteger, primary_key=True)
    slot_date = Column(Date, nullable=False)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    service_bay_id = Column(BigInteger, ForeignKey("app.service_bays.service_bay_id"))
    employee_id = Column(BigInteger, ForeignKey("app.employees.employee_id"))
    slot_status = Column(Text, nullable=False, default="Свободен")
    visit_id = Column(BigInteger, ForeignKey("app.service_visits.visit_id"))
    comment = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Promotion(Base):
    __tablename__ = "promotions"
    __table_args__ = {"schema": "app"}
    promotion_id = Column(BigInteger, primary_key=True)
    title = Column(Text, nullable=False)
    description = Column(Text)
    starts_at = Column(Date)
    ends_at = Column(Date)
    is_active = Column(Boolean, nullable=False, default=True)
    target_tags = Column(Text)
    target_car_brands = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PromotionContact(Base):
    __tablename__ = "promotion_contacts"
    __table_args__ = {"schema": "app"}
    contact_id = Column(BigInteger, primary_key=True)
    promotion_id = Column(BigInteger, ForeignKey("app.promotions.promotion_id"), nullable=False)
    client_id = Column(BigInteger, ForeignKey("app.clients.client_id"), nullable=False)
    car_id = Column(BigInteger, ForeignKey("app.cars.car_id"))
    contact_status = Column(Text, nullable=False, default="Запланировано")
    planned_date = Column(Date)
    contacted_at = Column(DateTime(timezone=True))
    result_comment = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class WorkOrder(Base):
    __tablename__ = "work_orders"
    __table_args__ = {"schema": "app"}
    work_order_id = Column(BigInteger, primary_key=True)
    order_number = Column(Text, nullable=False, unique=True)
    request_id = Column(BigInteger, ForeignKey("app.service_requests.request_id"))
    visit_id = Column(BigInteger, ForeignKey("app.service_visits.visit_id"))
    client_id = Column(BigInteger, ForeignKey("app.clients.client_id"), nullable=False)
    car_id = Column(BigInteger, ForeignKey("app.cars.car_id"), nullable=False)
    assigned_employee_id = Column(BigInteger, ForeignKey("app.employees.employee_id"))
    service_bay_id = Column(BigInteger, ForeignKey("app.service_bays.service_bay_id"))
    status = Column(Text, nullable=False, default="Создан")
    opened_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    closed_at = Column(DateTime(timezone=True))
    work_total = Column(Numeric(12, 2), nullable=False, default=0)
    parts_total = Column(Numeric(12, 2), nullable=False, default=0)
    parts_cost_total = Column(Numeric(12, 2), nullable=False, default=0)
    total_amount = Column(Numeric(12, 2), nullable=False, default=0)
    total_cost = Column(Numeric(12, 2), nullable=False, default=0)
    total_profit = Column(Numeric(12, 2), nullable=False, default=0)
    comment = Column(Text)


class WorkOrderItem(Base):
    __tablename__ = "work_order_items"
    __table_args__ = {"schema": "app"}
    item_id = Column(BigInteger, primary_key=True)
    work_order_id = Column(BigInteger, ForeignKey("app.work_orders.work_order_id", ondelete="CASCADE"), nullable=False)
    work_type = Column(Text, nullable=False)
    description = Column(Text)
    qty = Column(Numeric(10, 2), nullable=False, default=1)
    unit_price = Column(Numeric(12, 2), nullable=False, default=0)
    unit_cost = Column(Numeric(12, 2), nullable=False, default=0)
    line_total = Column(Numeric(12, 2), nullable=False, default=0)
    line_cost = Column(Numeric(12, 2), nullable=False, default=0)
    line_profit = Column(Numeric(12, 2), nullable=False, default=0)


class WorkOrderPart(Base):
    __tablename__ = "work_order_parts"
    __table_args__ = {"schema": "app"}
    part_id = Column(BigInteger, primary_key=True)
    work_order_id = Column(BigInteger, ForeignKey("app.work_orders.work_order_id", ondelete="CASCADE"), nullable=False)
    part_name = Column(Text, nullable=False)
    qty = Column(Numeric(10, 2), nullable=False, default=1)
    sale_price = Column(Numeric(12, 2), nullable=False, default=0)
    cost_price = Column(Numeric(12, 2), nullable=False, default=0)
    line_total = Column(Numeric(12, 2), nullable=False, default=0)
    line_cost = Column(Numeric(12, 2), nullable=False, default=0)
    line_profit = Column(Numeric(12, 2), nullable=False, default=0)


class WorkOrderStatusHistory(Base):
    __tablename__ = "work_order_status_history"
    __table_args__ = {"schema": "app"}
    history_id = Column(BigInteger, primary_key=True)
    work_order_id = Column(BigInteger, ForeignKey("app.work_orders.work_order_id", ondelete="CASCADE"), nullable=False)
    old_status = Column(Text)
    new_status = Column(Text, nullable=False)
    changed_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    changed_by = Column(Text)
    comment = Column(Text)
