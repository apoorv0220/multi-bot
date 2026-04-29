from typing import Any, Dict

import main as legacy_main


async def run_authenticated_chat(request, user_ctx, db) -> Dict[str, Any]:
    tenant_id = user_ctx["tenant_id"]
    if not tenant_id:
        raise legacy_main.HTTPException(status_code=400, detail="Tenant context missing")
    return await legacy_main._run_chat_for_tenant(request, tenant_id, user_ctx["user"].id, db)


async def run_public_chat(request, db, x_widget_key, x_visitor_id, origin, request_obj=None):
    if legacy_main.os.getenv("WIDGET_REQUIRE_ORIGIN", "false").lower() == "true" and not legacy_main._origin_allowed(origin):
        raise legacy_main.HTTPException(status_code=403, detail="Origin not allowed for widget")
    tenant_id = legacy_main._resolve_embed_tenant_id(x_widget_key)
    legacy_main._enforce_public_security_and_quota(db=db, tenant_id=tenant_id, request_obj=request_obj)
    visitor_id = legacy_main._normalize_visitor_id(x_visitor_id)
    visitor = legacy_main._get_visitor_profile(db, tenant_id, visitor_id)
    if not visitor:
        raise legacy_main.HTTPException(status_code=428, detail="Public visitor profile is required")
    actor_user_id = legacy_main._resolve_tenant_actor_user_id(db, tenant_id)
    return await legacy_main._run_chat_for_tenant(
        request,
        tenant_id,
        actor_user_id,
        db,
        is_public_chat=True,
        public_visitor=visitor,
    )
