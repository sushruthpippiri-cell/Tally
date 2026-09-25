from datetime import datetime

from pydantic import BaseModel


class RegistrationTokenOut(BaseModel):
    token: str  # shown once; only its hash is stored
    expires_at: datetime
