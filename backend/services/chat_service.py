import uuid
from typing import Any, Dict

from fastapi import HTTPException

from api.deps import (
    get_visitor_profile,
    normalize_visitor_id,
    resolve_embed_tenant_id,
    resolve_tenant_actor_user_id,
)
from models import Tenant
from services import public_security
from services.commerce_chat_service import run_chat_for_tenant


async def run_authenticated_chat(request, user_ctx, db) -> Dict[str, Any]:
    tenant_id = user_ctx["tenant_id"]
    if not tenant_id:
        raise HTTPException(status_code=400, detail="Tenant context missing")
    return await run_chat_for_tenant(request, tenant_id, user_ctx["user"].id, db)


async def run_public_chat(request, db, x_widget_key, x_visitor_id, origin, request_obj=None):
    tenant_id = resolve_embed_tenant_id(x_widget_key)
    tenant = db.get(Tenant, uuid.UUID(tenant_id))
    if not public_security.tenant_origin_allowed(
        tenant, public_security.effective_widget_origin(request_obj, origin)
    ):
        raise HTTPException(status_code=403, detail="Origin not allowed for widget")
    public_security.enforce_public_security_and_quota(db=db, tenant_id=tenant_id, request_obj=request_obj)
    visitor_id = normalize_visitor_id(x_visitor_id)
    visitor = get_visitor_profile(db, tenant_id, visitor_id)
    if not visitor:
        raise HTTPException(status_code=428, detail="Public visitor profile is required")
    actor_user_id = resolve_tenant_actor_user_id(db, tenant_id)
    return await run_chat_for_tenant(
        request,
        tenant_id,
        actor_user_id,
        db,
        is_public_chat=True,
        public_visitor=visitor,
    )
