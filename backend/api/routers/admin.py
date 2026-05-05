from typing import Optional

from fastapi import APIRouter, Depends, File, Query, UploadFile

import main as legacy_main
from services import admin_service, usage_service


router = APIRouter(tags=["admin"])


@router.get("/api/admin/chats")
async def admin_chats(
    user_ctx=Depends(legacy_main.get_current_user),
    db=Depends(legacy_main.db_session),
    q: Optional[str] = Query(default=None),
    tenant_id: Optional[str] = Query(default=None),
    page: int = Query(default=1),
    page_size: int = Query(default=20),
):
    return await admin_service.list_chats(
        user_ctx=user_ctx,
        db=db,
        q=q,
        tenant_id=tenant_id,
        page=page,
        page_size=page_size,
    )


@router.get("/api/admin/chats/{session_id}")
async def admin_chat_detail(session_id: str, user_ctx=Depends(legacy_main.get_current_user), db=Depends(legacy_main.db_session)):
    return await admin_service.chat_detail(session_id=session_id, user_ctx=user_ctx, db=db)


@router.get("/api/admin/users")
async def admin_users(
    user_ctx=Depends(legacy_main.get_current_user),
    db=Depends(legacy_main.db_session),
    tenant_id: Optional[str] = Query(default=None),
    page: int = Query(default=1),
    page_size: int = Query(default=20),
):
    return await admin_service.list_users(user_ctx=user_ctx, db=db, tenant_id=tenant_id, page=page, page_size=page_size)


@router.get("/api/admin/visitors")
async def admin_visitors(
    user_ctx=Depends(legacy_main.get_current_user),
    db=Depends(legacy_main.db_session),
    tenant_id: Optional[str] = Query(default=None),
    page: int = Query(default=1),
    page_size: int = Query(default=20),
):
    return await admin_service.list_visitors(user_ctx=user_ctx, db=db, tenant_id=tenant_id, page=page, page_size=page_size)


@router.get("/api/admin/visitors/{visitor_id}/chats")
async def admin_visitor_chats(
    visitor_id: str,
    user_ctx=Depends(legacy_main.get_current_user),
    db=Depends(legacy_main.db_session),
    tenant_id: Optional[str] = Query(default=None),
    page: int = Query(default=1),
    page_size: int = Query(default=20),
):
    return await admin_service.list_visitor_chats(
        visitor_id=visitor_id,
        user_ctx=user_ctx,
        db=db,
        tenant_id=tenant_id,
        page=page,
        page_size=page_size,
    )


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


@router.patch("/api/admin/tenants/{tenant_id}/branding")
async def update_tenant_branding(
    tenant_id: str,
    payload: legacy_main.TenantBrandingConfigRequest,
    user_ctx=Depends(legacy_main.get_current_user),
    db=Depends(legacy_main.db_session),
):
    return await admin_service.update_tenant_branding(tenant_id=tenant_id, payload=payload, user_ctx=user_ctx, db=db)


@router.post("/api/admin/tenants/{tenant_id}/avatar")
async def upload_tenant_avatar(
    tenant_id: str,
    file: UploadFile = File(...),
    user_ctx=Depends(legacy_main.get_current_user),
    db=Depends(legacy_main.db_session),
):
    return await admin_service.upload_tenant_avatar(tenant_id=tenant_id, file=file, user_ctx=user_ctx, db=db)


@router.get("/api/admin/reference/countries")
async def list_reference_countries(user_ctx=Depends(legacy_main.get_current_user)):
    return await admin_service.list_reference_countries(user_ctx=user_ctx)


@router.get("/api/admin/tenants/{tenant_id}/security")
async def get_tenant_security_settings(
    tenant_id: str,
    user_ctx=Depends(legacy_main.get_current_user),
    db=Depends(legacy_main.db_session),
):
    return await admin_service.get_tenant_security_settings(tenant_id=tenant_id, user_ctx=user_ctx, db=db)


@router.patch("/api/admin/tenants/{tenant_id}/quota")
async def update_tenant_quota_settings(
    tenant_id: str,
    payload: legacy_main.TenantQuotaConfigRequest,
    user_ctx=Depends(legacy_main.get_current_user),
    db=Depends(legacy_main.db_session),
):
    return await admin_service.update_tenant_quota_settings(tenant_id=tenant_id, payload=payload, user_ctx=user_ctx, db=db)


@router.patch("/api/admin/tenants/{tenant_id}/idle-rating")
async def update_tenant_idle_rating_settings(
    tenant_id: str,
    payload: legacy_main.TenantIdleRatingConfigRequest,
    user_ctx=Depends(legacy_main.get_current_user),
    db=Depends(legacy_main.db_session),
):
    return await admin_service.update_tenant_idle_rating_settings(tenant_id=tenant_id, payload=payload, user_ctx=user_ctx, db=db)


@router.post("/api/admin/tenants/{tenant_id}/blocked-ips")
async def add_tenant_blocked_ip(
    tenant_id: str,
    payload: legacy_main.BlockedIPRequest,
    user_ctx=Depends(legacy_main.get_current_user),
    db=Depends(legacy_main.db_session),
):
    return await admin_service.add_tenant_blocked_ip(tenant_id=tenant_id, payload=payload, user_ctx=user_ctx, db=db)


@router.delete("/api/admin/tenants/{tenant_id}/blocked-ips/{blocked_ip_id}")
async def remove_tenant_blocked_ip(
    tenant_id: str,
    blocked_ip_id: str,
    user_ctx=Depends(legacy_main.get_current_user),
    db=Depends(legacy_main.db_session),
):
    return await admin_service.remove_tenant_blocked_ip(
        tenant_id=tenant_id,
        blocked_ip_id=blocked_ip_id,
        user_ctx=user_ctx,
        db=db,
    )


@router.post("/api/admin/tenants/{tenant_id}/blocked-countries")
async def add_tenant_blocked_country(
    tenant_id: str,
    payload: legacy_main.BlockedCountryRequest,
    user_ctx=Depends(legacy_main.get_current_user),
    db=Depends(legacy_main.db_session),
):
    return await admin_service.add_tenant_blocked_country(tenant_id=tenant_id, payload=payload, user_ctx=user_ctx, db=db)


@router.delete("/api/admin/tenants/{tenant_id}/blocked-countries/{blocked_country_id}")
async def remove_tenant_blocked_country(
    tenant_id: str,
    blocked_country_id: str,
    user_ctx=Depends(legacy_main.get_current_user),
    db=Depends(legacy_main.db_session),
):
    return await admin_service.remove_tenant_blocked_country(
        tenant_id=tenant_id,
        blocked_country_id=blocked_country_id,
        user_ctx=user_ctx,
        db=db,
    )


@router.get("/api/admin/tenants/{tenant_id}/block-word-categories")
async def list_block_word_categories(
    tenant_id: str,
    user_ctx=Depends(legacy_main.get_current_user),
    db=Depends(legacy_main.db_session),
):
    return await admin_service.list_block_word_categories(tenant_id=tenant_id, user_ctx=user_ctx, db=db)


@router.post("/api/admin/tenants/{tenant_id}/block-word-categories")
async def create_block_word_category(
    tenant_id: str,
    payload: legacy_main.BlockWordCategoryRequest,
    user_ctx=Depends(legacy_main.get_current_user),
    db=Depends(legacy_main.db_session),
):
    return await admin_service.create_block_word_category(tenant_id=tenant_id, payload=payload, user_ctx=user_ctx, db=db)


@router.patch("/api/admin/tenants/{tenant_id}/block-word-categories/{category_id}")
async def update_block_word_category(
    tenant_id: str,
    category_id: str,
    payload: legacy_main.BlockWordCategoryRequest,
    user_ctx=Depends(legacy_main.get_current_user),
    db=Depends(legacy_main.db_session),
):
    return await admin_service.update_block_word_category(
        tenant_id=tenant_id,
        category_id=category_id,
        payload=payload,
        user_ctx=user_ctx,
        db=db,
    )


@router.delete("/api/admin/tenants/{tenant_id}/block-word-categories/{category_id}")
async def delete_block_word_category(
    tenant_id: str,
    category_id: str,
    user_ctx=Depends(legacy_main.get_current_user),
    db=Depends(legacy_main.db_session),
):
    return await admin_service.delete_block_word_category(tenant_id=tenant_id, category_id=category_id, user_ctx=user_ctx, db=db)


@router.post("/api/admin/tenants/{tenant_id}/block-word-categories/{category_id}/words")
async def add_block_word(
    tenant_id: str,
    category_id: str,
    payload: legacy_main.BlockWordRequest,
    user_ctx=Depends(legacy_main.get_current_user),
    db=Depends(legacy_main.db_session),
):
    return await admin_service.add_block_word(
        tenant_id=tenant_id,
        category_id=category_id,
        payload=payload,
        user_ctx=user_ctx,
        db=db,
    )


@router.delete("/api/admin/tenants/{tenant_id}/block-word-categories/{category_id}/words/{word_id}")
async def delete_block_word(
    tenant_id: str,
    category_id: str,
    word_id: str,
    user_ctx=Depends(legacy_main.get_current_user),
    db=Depends(legacy_main.db_session),
):
    return await admin_service.delete_block_word(
        tenant_id=tenant_id,
        category_id=category_id,
        word_id=word_id,
        user_ctx=user_ctx,
        db=db,
    )


@router.get("/api/admin/tenants/{tenant_id}/quick-replies")
async def list_quick_replies(
    tenant_id: str,
    user_ctx=Depends(legacy_main.get_current_user),
    db=Depends(legacy_main.db_session),
):
    return await admin_service.list_quick_replies(tenant_id=tenant_id, user_ctx=user_ctx, db=db)


@router.post("/api/admin/tenants/{tenant_id}/quick-replies")
async def create_quick_reply(
    tenant_id: str,
    payload: legacy_main.QuickReplyCreateRequest,
    user_ctx=Depends(legacy_main.get_current_user),
    db=Depends(legacy_main.db_session),
):
    return await admin_service.create_quick_reply(tenant_id=tenant_id, payload=payload, user_ctx=user_ctx, db=db)


@router.patch("/api/admin/tenants/{tenant_id}/quick-replies/{quick_reply_id}")
async def update_quick_reply(
    tenant_id: str,
    quick_reply_id: str,
    payload: legacy_main.QuickReplyUpdateRequest,
    user_ctx=Depends(legacy_main.get_current_user),
    db=Depends(legacy_main.db_session),
):
    return await admin_service.update_quick_reply(
        tenant_id=tenant_id,
        quick_reply_id=quick_reply_id,
        payload=payload,
        user_ctx=user_ctx,
        db=db,
    )


@router.delete("/api/admin/tenants/{tenant_id}/quick-replies/{quick_reply_id}")
async def delete_quick_reply(
    tenant_id: str,
    quick_reply_id: str,
    user_ctx=Depends(legacy_main.get_current_user),
    db=Depends(legacy_main.db_session),
):
    return await admin_service.delete_quick_reply(
        tenant_id=tenant_id,
        quick_reply_id=quick_reply_id,
        user_ctx=user_ctx,
        db=db,
    )


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
