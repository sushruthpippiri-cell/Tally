from pydantic import BaseModel, Field, field_validator


def check_password(value: str) -> str:
    if len(value) < 8:
        raise ValueError("password must be at least 8 characters")
    if len(value.encode()) > 72:
        raise ValueError("password must be at most 72 bytes")
    return value


class LoginRequest(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=1024)


class RefreshRequest(BaseModel):
    refresh_token: str


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(max_length=1024)
    new_password: str

    _new = field_validator("new_password")(check_password)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds until the access token expires
