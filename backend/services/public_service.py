import uuid

from fastapi import HTTPException

import main as legacy_main
from api.deps import (
    get_visitor_profile,
    get_visitor_profile_by_email,
    normalize_visitor_email,
    normalize_visitor_id,
    resolve_embed_tenant_id,
    resolve_tenant_actor_user_id,
)
from models import ChatVisitor, Tenant


async def get_visitor_profile(*, db, x_widget_key, x_visitor_id, origin, request_obj=None):
    tenant_id = resolve_embed_tenant_id(x_widget_key)
    tenant = db.get(Tenant, uuid.UUID(tenant_id))
    if not legacy_main._tenant_origin_allowed(
        tenant, legacy_main._effective_widget_origin(request_obj, origin)
    ):
        raise HTTPException(status_code=403, detail="Origin not allowed for widget")
    legacy_main._enforce_public_security_and_quota(
        db=db,
        tenant_id=tenant_id,
        request_obj=request_obj,
        apply_ip_country_blocks=False,
        apply_message_quota=False,
    )
    visitor_id = normalize_visitor_id(x_visitor_id)
    visitor = get_visitor_profile(db, tenant_id, visitor_id)
    return {"profile_exists": bool(visitor)}


async def upsert_visitor_profile(*, payload, db, x_widget_key, origin, request_obj=None):
    tenant_id = resolve_embed_tenant_id(x_widget_key)
    tenant = db.get(Tenant, uuid.UUID(tenant_id))
    if not legacy_main._tenant_origin_allowed(
        tenant, legacy_main._effective_widget_origin(request_obj, origin)
    ):
        raise HTTPException(status_code=403, detail="Origin not allowed for widget")
    legacy_main._enforce_public_security_and_quota(
        db=db,
        tenant_id=tenant_id,
        request_obj=request_obj,
        apply_ip_country_blocks=False,
        apply_message_quota=False,
    )
    visitor_id = normalize_visitor_id(payload.visitor_id)
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    email_trimmed, email_normalized = normalize_visitor_email(str(payload.email))
    visitor = get_visitor_profile(db, tenant_id, visitor_id)
    if visitor:
        visitor.name = name
        visitor.email = email_trimmed
        resolved_visitor_id = visitor.visitor_id
    else:
        canonical = get_visitor_profile_by_email(db, tenant_id, email_normalized)
        if canonical:
            canonical.name = name
            canonical.email = email_trimmed
            resolved_visitor_id = canonical.visitor_id
        else:
            db.add(
                ChatVisitor(
                    tenant_id=uuid.UUID(tenant_id),
                    visitor_id=visitor_id,
                    name=name,
                    email=email_trimmed,
                )
            )
            resolved_visitor_id = visitor_id
    db.commit()
    return {"status": "ok", "profile_exists": True, "visitor_id": resolved_visitor_id}


async def add_public_feedback(*, message_id, payload, db, x_widget_key, origin, request_obj=None):
    tenant_id = resolve_embed_tenant_id(x_widget_key)
    tenant = db.get(Tenant, uuid.UUID(tenant_id))
    if not legacy_main._tenant_origin_allowed(
        tenant, legacy_main._effective_widget_origin(request_obj, origin)
    ):
        raise HTTPException(status_code=403, detail="Origin not allowed for widget")
    legacy_main._enforce_public_security_and_quota(
        db=db,
        tenant_id=tenant_id,
        request_obj=request_obj,
        apply_ip_country_blocks=False,
        apply_message_quota=False,
    )
    message = db.get(legacy_main.ChatMessage, legacy_main.uuid.UUID(message_id))
    if not message:
        raise legacy_main.HTTPException(status_code=404, detail="Message not found")
    if str(message.tenant_id) != tenant_id:
        raise legacy_main.HTTPException(status_code=403, detail="Forbidden")
    session = db.get(legacy_main.ChatSession, message.session_id)
    actor_user_id = session.created_by_user_id if session else resolve_tenant_actor_user_id(db, tenant_id)
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


async def get_widget_config(*, db, x_widget_key, origin, request_obj):
    return await legacy_main.get_public_widget_config(
        request_obj=request_obj,
        db=db,
        x_widget_key=x_widget_key,
        origin=origin,
    )


async def get_session_rating_status(*, session_id, db, x_widget_key, x_visitor_id, origin, request_obj=None):
    return await legacy_main.get_public_session_rating_status(
        session_id=session_id,
        db=db,
        x_widget_key=x_widget_key,
        x_visitor_id=x_visitor_id,
        origin=origin,
        request_obj=request_obj,
    )


async def submit_session_rating(*, payload, db, x_widget_key, x_visitor_id, origin, request_obj=None):
    return await legacy_main.submit_public_session_rating(
        payload=payload,
        db=db,
        x_widget_key=x_widget_key,
        x_visitor_id=x_visitor_id,
        origin=origin,
        request_obj=request_obj,
    )
