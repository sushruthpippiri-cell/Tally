import uuid
from datetime import date
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator

from app.models.enums import RoleName


def check_timezone(value: str) -> str:
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"unknown IANA time zone: {value!r}") from exc
    return value


def check_fy_start(value: date) -> date:
    # D-034: every year has days 1-28, so quarter boundaries always exist.
    if value.day > 28:
        raise ValueError("financial year must start on day 1-28 of a month")
    return value


class CompanyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    financial_year_start: date
    company_timezone: str

    _tz = field_validator("company_timezone")(check_timezone)
    _fy = field_validator("financial_year_start")(check_fy_start)


class CompanyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    financial_year_start: date | None = None
    company_timezone: str | None = None

    @field_validator("company_timezone")
    @classmethod
    def _tz(cls, value: str | None) -> str | None:
        return None if value is None else check_timezone(value)

    @field_validator("financial_year_start")
    @classmethod
    def _fy(cls, value: date | None) -> date | None:
        return None if value is None else check_fy_start(value)


class CompanyOut(BaseModel):
    company_id: uuid.UUID
    name: str
    financial_year_start: date
    company_timezone: str
    is_active: bool
    tally_guid: str | None
    my_roles: list[RoleName]
