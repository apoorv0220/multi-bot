import json
import logging
import os
import uuid
from typing import Dict, Optional

from fastapi import Depends, Header, HTTPException
from sqlalchemy import func, select

from auth import decode_token
from core.policies import require_role as policy_require_role
from core.policies import resolve_effective_tenant_id_for_admin_views as policy_resolve_effective_tenant_id
from db import SessionLocal
from models import ChatVisitor, User, UserTenant

logger = logging.getLogger("chatbot-api")


def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    authorization: Optional[str] = Header(default=None),
    db=Depends(db_session),
):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1]
    try:
        payload = decode_token(token)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc

    user = db.get(User, uuid.UUID(payload["sub"]))
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    return {
        "user": user,
        "tenant_id": payload.get("tenant_id"),
        "role": payload.get("role"),
    }


def require_role(user_ctx: dict, roles: list[str]):
    policy_require_role(user_ctx, roles)


def _load_widget_embed_key_map() -> Dict[str, str]:
    raw = os.getenv("WIDGET_EMBED_KEYS_JSON", "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("Invalid WIDGET_EMBED_KEYS_JSON: %s", exc)
        return {}
    if not isinstance(parsed, dict):
        logger.warning("WIDGET_EMBED_KEYS_JSON must be a JSON object")
        return {}
    return {str(k): str(v) for k, v in parsed.items() if k and v}


def resolve_embed_tenant_id(embed_key: Optional[str]) -> str:
    if not embed_key:
        raise HTTPException(status_code=401, detail="Missing widget key")
    key_map = _load_widget_embed_key_map()
    tenant_id = key_map.get(embed_key)
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Invalid widget key")
    return tenant_id


def resolve_tenant_actor_user_id(db, tenant_id: str) -> uuid.UUID:
    members = db.execute(
        select(UserTenant).where(UserTenant.tenant_id == uuid.UUID(tenant_id)).order_by(UserTenant.created_at.asc())
    ).scalars().all()
    if not members:
        raise HTTPException(status_code=400, detail="No tenant user available for widget chat")
    for member in members:
        user = db.get(User, member.user_id)
        if user and user.is_active:
            return user.id
    raise HTTPException(status_code=400, detail="No active tenant user available for widget chat")


def resolve_effective_tenant_id_for_admin_views(db, user_ctx: dict, tenant_id: Optional[str]) -> str:
    return policy_resolve_effective_tenant_id(db, user_ctx, tenant_id)


def normalize_visitor_id(visitor_id: Optional[str]) -> str:
    normalized = (visitor_id or "").strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="visitor_id is required")
    if len(normalized) > 64:
        raise HTTPException(status_code=400, detail="visitor_id is invalid")
    return normalized


def get_visitor_profile(db, tenant_id: str, visitor_id: str) -> Optional[ChatVisitor]:
    return db.execute(
        select(ChatVisitor).where(
            ChatVisitor.tenant_id == uuid.UUID(tenant_id),
            ChatVisitor.visitor_id == visitor_id,
        )
    ).scalar_one_or_none()


def normalize_visitor_email(email: str) -> tuple[str, str]:
    trimmed = (email or "").strip()
    if not trimmed:
        raise HTTPException(status_code=400, detail="email is required")
    return trimmed, trimmed.lower()


def get_visitor_profile_by_email(db, tenant_id: str, email_normalized: str) -> Optional[ChatVisitor]:
    return db.execute(
        select(ChatVisitor)
        .where(
            ChatVisitor.tenant_id == uuid.UUID(tenant_id),
            func.lower(ChatVisitor.email) == email_normalized,
        )
        .order_by(ChatVisitor.updated_at.desc())
    ).scalars().first()
