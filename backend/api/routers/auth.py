from fastapi import APIRouter, Depends

import main as legacy_main


router = APIRouter(tags=["auth"])


@router.post("/api/auth/register", response_model=legacy_main.AuthResponse)
async def register(payload: legacy_main.AuthRequest, db=Depends(legacy_main.db_session)):
    return await legacy_main.register(payload=payload, db=db)


@router.post("/api/auth/login", response_model=legacy_main.AuthResponse)
async def login(payload: legacy_main.AuthRequest, db=Depends(legacy_main.db_session)):
    return await legacy_main.login(payload=payload, db=db)
