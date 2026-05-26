from typing import Optional

from fastapi import APIRouter, Depends, Query

import main as legacy_main
from api.deps import db_session, get_current_user
from api.schemas import ReindexRequest
from services import reindex_service


router = APIRouter(tags=["reindex"])


@router.post("/api/reindex")
async def trigger_reindex(
    request: ReindexRequest,
    user_ctx=Depends(get_current_user),
    db=Depends(db_session),
):
    return await reindex_service.trigger_reindex(request=request, user_ctx=user_ctx, db=db)


@router.get("/api/reindex/jobs")
async def list_reindex_jobs(
    user_ctx=Depends(get_current_user),
    db=Depends(db_session),
    tenant_id: Optional[str] = Query(default=None),
):
    return await reindex_service.list_reindex_jobs(user_ctx=user_ctx, db=db, tenant_id=tenant_id)
