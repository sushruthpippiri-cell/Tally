import uuid

from pydantic import BaseModel, Field, field_validator

from app.core.security import normalize_email
from app.models.enums import RoleName
from app.schemas.auth import check_password


def _roles(value: list[RoleName]) -> list[RoleName]:
    return sorted(set(value))


class UserCreate(BaseModel):
    email: str = Field(max_length=320)
    name: str = Field(min_length=1, max_length=200)
    password: str  # ignored when the email already has an account (D-033 #8)
    roles: list[RoleName] = Field(min_length=1)

    _password = field_validator("password")(check_password)
    _r = field_validator("roles")(_roles)

    @field_validator("email")
    @classmethod
    def _email(cls, value: str) -> str:
        value = normalize_email(value)
        local, _, domain = value.partition("@")
        if not local or "." not in domain or " " in value:
            raise ValueError("not an email address")
        return value


class RolesUpdate(BaseModel):
    roles: list[RoleName]  # replaces the user's roles in this company; [] removes access

    _r = field_validator("roles")(_roles)


class CompanyUserOut(BaseModel):
    user_id: uuid.UUID
    email: str
    name: str
    is_active: bool
    roles: list[RoleName]
