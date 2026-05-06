from fastapi import APIRouter

import main as legacy_main


router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    return await legacy_main.health_check()
