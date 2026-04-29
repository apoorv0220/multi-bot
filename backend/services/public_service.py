import main as legacy_main


async def get_visitor_profile(*, db, x_widget_key, x_visitor_id, origin, request_obj=None):
    if legacy_main.os.getenv("WIDGET_REQUIRE_ORIGIN", "false").lower() == "true" and not legacy_main._origin_allowed(origin):
        raise legacy_main.HTTPException(status_code=403, detail="Origin not allowed for widget")
    tenant_id = legacy_main._resolve_embed_tenant_id(x_widget_key)
    legacy_main._enforce_public_security_and_quota(db=db, tenant_id=tenant_id, request_obj=request_obj)
    visitor_id = legacy_main._normalize_visitor_id(x_visitor_id)
    visitor = legacy_main._get_visitor_profile(db, tenant_id, visitor_id)
    return {"profile_exists": bool(visitor)}


async def upsert_visitor_profile(*, payload, db, x_widget_key, origin, request_obj=None):
    if legacy_main.os.getenv("WIDGET_REQUIRE_ORIGIN", "false").lower() == "true" and not legacy_main._origin_allowed(origin):
        raise legacy_main.HTTPException(status_code=403, detail="Origin not allowed for widget")
    tenant_id = legacy_main._resolve_embed_tenant_id(x_widget_key)
    legacy_main._enforce_public_security_and_quota(db=db, tenant_id=tenant_id, request_obj=request_obj)
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


async def add_public_feedback(*, message_id, payload, db, x_widget_key, origin, request_obj=None):
    if legacy_main.os.getenv("WIDGET_REQUIRE_ORIGIN", "false").lower() == "true" and not legacy_main._origin_allowed(origin):
        raise legacy_main.HTTPException(status_code=403, detail="Origin not allowed for widget")
    tenant_id = legacy_main._resolve_embed_tenant_id(x_widget_key)
    legacy_main._enforce_public_security_and_quota(db=db, tenant_id=tenant_id, request_obj=request_obj)
    message = db.get(legacy_main.ChatMessage, legacy_main.uuid.UUID(message_id))
    if not message:
        raise legacy_main.HTTPException(status_code=404, detail="Message not found")
    if str(message.tenant_id) != tenant_id:
        raise legacy_main.HTTPException(status_code=403, detail="Forbidden")
    session = db.get(legacy_main.ChatSession, message.session_id)
    actor_user_id = session.created_by_user_id if session else legacy_main._resolve_tenant_actor_user_id(db, tenant_id)
    feedback = db.execute(
        legacy_main.select(legacy_main.MessageFeedback).where(
            legacy_main.MessageFeedback.message_id == message.id,
            legacy_main.MessageFeedback.user_id == actor_user_id,
        )
    ).scalar_one_or_none()
    if feedback:
        feedback.vote = payload.vote
        feedback.reason = payload.reason or ""
    else:
        db.add(
            legacy_main.MessageFeedback(
                tenant_id=message.tenant_id,
                message_id=message.id,
                user_id=actor_user_id,
                vote=payload.vote,
                reason=payload.reason or "",
            )
        )
    db.commit()
    return {"status": "ok"}
