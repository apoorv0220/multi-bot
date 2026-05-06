from typing import Optional

from fastapi import APIRouter, Depends, Query

import main as legacy_main
from services import reindex_service


router = APIRouter(tags=["reindex"])


@router.post("/api/reindex")
async def trigger_reindex(
    request: legacy_main.ReindexRequest,
    user_ctx=Depends(legacy_main.get_current_user),
    db=Depends(legacy_main.db_session),
):
    return await reindex_service.trigger_reindex(request=request, user_ctx=user_ctx, db=db)


@router.get("/api/reindex/jobs")
async def list_reindex_jobs(
    user_ctx=Depends(legacy_main.get_current_user),
    db=Depends(legacy_main.db_session),
    tenant_id: Optional[str] = Query(default=None),
):
    return await reindex_service.list_reindex_jobs(user_ctx=user_ctx, db=db, tenant_id=tenant_id)
