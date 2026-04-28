from typing import Optional
import uuid

from fastapi import HTTPException
from sqlalchemy import select

from models import Tenant, UserRole, UserTenant


def require_role(user_ctx: dict, roles: list[str]):
    if user_ctx["role"] not in roles:
        raise HTTPException(status_code=403, detail="Insufficient permissions")


def resolve_effective_tenant_id_for_admin_views(db, user_ctx: dict, tenant_id: Optional[str]) -> str:
    if user_ctx["role"] == UserRole.superadmin.value:
        if tenant_id:
            return tenant_id
        first_tenant = db.execute(select(Tenant).order_by(Tenant.created_at.asc())).scalars().first()
        if not first_tenant:
            raise HTTPException(status_code=400, detail="No tenants available")
        return str(first_tenant.id)

    accessible_tenant_ids = get_accessible_tenant_ids(db, user_ctx)
    if not accessible_tenant_ids:
        raise HTTPException(status_code=400, detail="Tenant context missing")
    if tenant_id:
        if tenant_id not in accessible_tenant_ids:
            raise HTTPException(status_code=403, detail="Forbidden")
        return tenant_id
    if user_ctx.get("tenant_id") and user_ctx["tenant_id"] in accessible_tenant_ids:
        return user_ctx["tenant_id"]
    return accessible_tenant_ids[0]


def get_accessible_tenant_ids(db, user_ctx: dict) -> list[str]:
    if user_ctx["role"] == UserRole.superadmin.value:
        return [str(tid) for tid in db.execute(select(Tenant.id)).scalars().all()]
    user_id = user_ctx["user"].id if hasattr(user_ctx.get("user"), "id") else user_ctx["user"]["id"]
    rows = db.execute(select(UserTenant.tenant_id).where(UserTenant.user_id == user_id)).scalars().all()
    return [str(tid) for tid in rows]


def can_access_tenant(db, user_ctx: dict, tenant_id: str) -> bool:
    if user_ctx["role"] == UserRole.superadmin.value:
        return True
    return tenant_id in get_accessible_tenant_ids(db, user_ctx)


def ensure_tenant_access(db, user_ctx: dict, tenant_id: str):
    try:
        uuid.UUID(tenant_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid tenant id") from exc
    if not can_access_tenant(db, user_ctx, tenant_id):
        raise HTTPException(status_code=403, detail="Forbidden")
