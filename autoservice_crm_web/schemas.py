from datetime import date
from pydantic import BaseModel, field_validator


class IncomingRequestSchema(BaseModel):
    @field_validator("car_year", "desired_visit_date", mode="before")
    @classmethod
    def empty_string_to_none(cls, value):
        if value is None:
            return None
        if isinstance(value, str) and value.strip() == "":
            return None
        return value

    external_request_id: str | None = None
    full_name: str
    phone: str
    email: str | None = None
    car_brand: str
    car_model: str
    car_year: int | None = None
    car_plate: str
    problem_description: str
    urgency: str | None = None
    desired_visit_date: date | None = None
    preferred_contact_slot: str | None = None
    client_comment: str | None = None
    parts_mode: str | None = None
    source_system: str = "web_form"
    raw_payload: dict | None = None
