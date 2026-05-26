from typing import List, Optional

from pydantic import BaseModel, EmailStr


class AuthRequest(BaseModel):
    email: EmailStr
    password: str


class AuthResponse(BaseModel):
    access_token: str
    role: str
    tenant_id: Optional[str] = None
    tenant_ids: List[str] = []
