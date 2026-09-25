"""Company, users and access (SRS 5.3)."""

import uuid
from datetime import date, datetime

from sqlalchemy import ForeignKey, Index, SmallInteger, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at, enum_check, uuid_pk
from app.models.enums import RoleName


class Company(Base):
    __tablename__ = "companies"

    company_id: Mapped[uuid.UUID] = uuid_pk()
    tally_guid: Mapped[str | None] = mapped_column(unique=True)  # null until an Agent registers
    name: Mapped[str]
    financial_year_start: Mapped[date]
    company_timezone: Mapped[str]  # IANA name; validated by the API (P2)
    is_active: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
    created_at: Mapped[datetime] = created_at()


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        # D-031: case-insensitive, so Owner@x and owner@x are one account.
        Index("uq_users_email_lower", func.lower(text("email")), unique=True),
    )

    user_id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str]
    password_hash: Mapped[str]  # bcrypt
    name: Mapped[str]
    is_active: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
    created_at: Mapped[datetime] = created_at()


class Role(Base):
    __tablename__ = "roles"
    __table_args__ = (enum_check("role_name", RoleName),)

    role_id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    role_name: Mapped[str] = mapped_column(unique=True)


class UserRole(Base):
    __tablename__ = "user_roles"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.user_id"), primary_key=True)
    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.company_id"), primary_key=True, index=True
    )
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.role_id"), primary_key=True)


class RefreshToken(Base):
    """One row per issued refresh token, so a refresh can rotate it and reuse is detected
    (D-033). `used_at` set = rotated; a revoked token (password change, detected reuse) is
    deleted, so presenting it is a plain 401 rather than another reuse alarm."""

    __tablename__ = "refresh_tokens"

    jti: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.user_id"), index=True)
    expires_at: Mapped[datetime]
    used_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = created_at()
