import main as legacy_main


async def get_visitor_profile(*, db, x_widget_key, x_visitor_id, origin):
    if legacy_main.os.getenv("WIDGET_REQUIRE_ORIGIN", "false").lower() == "true" and not legacy_main._origin_allowed(origin):
        raise legacy_main.HTTPException(status_code=403, detail="Origin not allowed for widget")
    tenant_id = legacy_main._resolve_embed_tenant_id(x_widget_key)
    visitor_id = legacy_main._normalize_visitor_id(x_visitor_id)
    visitor = legacy_main._get_visitor_profile(db, tenant_id, visitor_id)
    return {"profile_exists": bool(visitor)}


async def upsert_visitor_profile(*, payload, db, x_widget_key, origin):
    if legacy_main.os.getenv("WIDGET_REQUIRE_ORIGIN", "false").lower() == "true" and not legacy_main._origin_allowed(origin):
        raise legacy_main.HTTPException(status_code=403, detail="Origin not allowed for widget")
    tenant_id = legacy_main._resolve_embed_tenant_id(x_widget_key)
    visitor_id = legacy_main._normalize_visitor_id(payload.visitor_id)
    name = payload.name.strip()
    if not name:
        raise legacy_main.HTTPException(status_code=400, detail="name is required")
    visitor = legacy_main._get_visitor_profile(db, tenant_id, visitor_id)
    if visitor:
        visitor.name = name
        visitor.email = payload.email
    else:
        db.add(
            legacy_main.ChatVisitor(
                tenant_id=legacy_main.uuid.UUID(tenant_id),
                visitor_id=visitor_id,
                name=name,
                email=payload.email,
            )
        )
    db.commit()
    return {"status": "ok", "profile_exists": True}
