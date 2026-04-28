from typing import Optional

from fastapi import APIRouter, Depends, Query

import main as legacy_main
from services import admin_service, usage_service


router = APIRouter(tags=["admin"])


@router.get("/api/admin/chats")
async def admin_chats(
    user_ctx=Depends(legacy_main.get_current_user),
    db=Depends(legacy_main.db_session),
    q: Optional[str] = Query(default=None),
    tenant_id: Optional[str] = Query(default=None),
):
    return await admin_service.list_chats(user_ctx=user_ctx, db=db, q=q, tenant_id=tenant_id)


@router.get("/api/admin/chats/{session_id}")
async def admin_chat_detail(session_id: str, user_ctx=Depends(legacy_main.get_current_user), db=Depends(legacy_main.db_session)):
    return await admin_service.chat_detail(session_id=session_id, user_ctx=user_ctx, db=db)


@router.get("/api/admin/users")
async def admin_users(
    user_ctx=Depends(legacy_main.get_current_user),
    db=Depends(legacy_main.db_session),
    tenant_id: Optional[str] = Query(default=None),
):
    return await admin_service.list_users(user_ctx=user_ctx, db=db, tenant_id=tenant_id)


@router.get("/api/admin/tenants")
async def admin_tenants(user_ctx=Depends(legacy_main.get_current_user), db=Depends(legacy_main.db_session)):
    return await admin_service.list_tenants(user_ctx=user_ctx, db=db)


@router.patch("/api/admin/tenants/{tenant_id}/source-config")
async def update_tenant_source_config(
    tenant_id: str,
    payload: legacy_main.TenantSourceConfigRequest,
    user_ctx=Depends(legacy_main.get_current_user),
    db=Depends(legacy_main.db_session),
):
    return await admin_service.update_tenant_source_config(tenant_id=tenant_id, payload=payload, user_ctx=user_ctx, db=db)


@router.post("/api/admin/users")
async def create_admin_user(payload: legacy_main.AdminCreateRequest, user_ctx=Depends(legacy_main.get_current_user), db=Depends(legacy_main.db_session)):
    return await admin_service.create_admin_user(payload=payload, user_ctx=user_ctx, db=db)


@router.post("/api/admin/users/{user_id}/status")
async def update_user_status(
    user_id: str,
    payload: legacy_main.UserStatusRequest,
    user_ctx=Depends(legacy_main.get_current_user),
    db=Depends(legacy_main.db_session),
):
    return await admin_service.update_user_status(user_id=user_id, payload=payload, user_ctx=user_ctx, db=db)


@router.post("/api/admin/users/{user_id}/reset-password")
async def reset_user_password(
    user_id: str,
    payload: legacy_main.ResetPasswordRequest,
    user_ctx=Depends(legacy_main.get_current_user),
    db=Depends(legacy_main.db_session),
):
    return await admin_service.reset_user_password(user_id=user_id, payload=payload, user_ctx=user_ctx, db=db)


@router.get("/api/admin/usage/summary")
async def admin_usage_summary(
    user_ctx=Depends(legacy_main.get_current_user),
    db=Depends(legacy_main.db_session),
    tenant_id: Optional[str] = Query(default=None),
):
    return await usage_service.usage_summary(user_ctx=user_ctx, db=db, tenant_id=tenant_id)


@router.get("/api/admin/overview")
async def admin_overview(
    user_ctx=Depends(legacy_main.get_current_user),
    db=Depends(legacy_main.db_session),
    tenant_id: Optional[str] = Query(default=None),
):
    return await usage_service.overview(user_ctx=user_ctx, db=db, tenant_id=tenant_id)
