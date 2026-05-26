from fastapi import APIRouter, Depends

import main as legacy_main
from api.deps import db_session
from api.schemas import AuthRequest, AuthResponse


router = APIRouter(tags=["auth"])


@router.post("/api/auth/register", response_model=AuthResponse)
async def register(payload: AuthRequest, db=Depends(db_session)):
    return await legacy_main.register(payload=payload, db=db)


@router.post("/api/auth/login", response_model=AuthResponse)
async def login(payload: AuthRequest, db=Depends(db_session)):
    return await legacy_main.login(payload=payload, db=db)
