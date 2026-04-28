from typing import Optional
import uuid

from fastapi import HTTPException
from sqlalchemy import select

from models import Tenant, UserRole


def require_role(user_ctx: dict, roles: list[str]):
    if user_ctx["role"] not in roles:
        raise HTTPException(status_code=403, detail="Insufficient permissions")


def resolve_effective_tenant_id_for_admin_views(db, user_ctx: dict, tenant_id: Optional[str]) -> str:
    if user_ctx["role"] != UserRole.superadmin.value:
        if not user_ctx.get("tenant_id"):
            raise HTTPException(status_code=400, detail="Tenant context missing")
        return user_ctx["tenant_id"]
    if tenant_id:
        return tenant_id
    first_tenant = db.execute(select(Tenant).order_by(Tenant.created_at.asc())).scalars().first()
    if not first_tenant:
        raise HTTPException(status_code=400, detail="No tenants available")
    return str(first_tenant.id)


def can_access_tenant(user_ctx: dict, tenant_id: str) -> bool:
    if user_ctx["role"] == UserRole.superadmin.value:
        return True
    return user_ctx.get("tenant_id") == tenant_id


def ensure_tenant_access(user_ctx: dict, tenant_id: str):
    try:
        uuid.UUID(tenant_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid tenant id") from exc
    if not can_access_tenant(user_ctx, tenant_id):
        raise HTTPException(status_code=403, detail="Forbidden")
