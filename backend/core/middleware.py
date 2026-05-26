import logging
import os
import uuid
from typing import Optional
from urllib.parse import urlparse

from fastapi import Request
from fastapi.responses import JSONResponse

from auth import decode_token
from api.deps import resolve_embed_tenant_id
from db import SessionLocal
from models import Tenant

logger = logging.getLogger("chatbot-api")


def origin_allowed(origin: Optional[str]) -> bool:
    allowed = os.getenv("WIDGET_ALLOWED_ORIGINS", "*").strip()
    if allowed == "*":
        return True
    allowed_set = {item.strip() for item in allowed.split(",") if item.strip()}
    if not allowed_set:
        return True
    return bool(origin and origin in allowed_set)


def tenant_origin_allowed(tenant: Optional[Tenant], origin: Optional[str]) -> bool:
    if tenant and tenant.cors_allowed_origins:
        allowed = {item.strip() for item in tenant.cors_allowed_origins.split(",") if item.strip()}
        if "*" in allowed:
            return True
        return bool(origin and origin in allowed)
    return origin_allowed(origin)


def effective_widget_origin(request: Optional[Request], origin: Optional[str]) -> Optional[str]:
    """Browser `Origin` is often omitted on same-origin GET; fall back to `Referer` scheme+host."""
    if origin:
        stripped = origin.strip()
        if stripped:
            return stripped
    if request is None:
        return None
    referer = request.headers.get("referer") or request.headers.get("Referer")
    if not referer:
        return None
    try:
        parsed = urlparse(referer)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
    except Exception:
        return None
    return None


async def exception_handling_middleware(request: Request, call_next):
    try:
        response = await call_next(request)
        logger.info("%s %s -> %s", request.method, request.url.path, response.status_code)
        return response
    except Exception:
        logger.exception("Unhandled error for %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )


async def tenant_cors_enforcement_middleware(request: Request, call_next):
    effective_origin = effective_widget_origin(request, request.headers.get("origin"))
    if not effective_origin or not request.url.path.startswith("/api/"):
        return await call_next(request)
    is_public_api = request.url.path.startswith("/api/public/")

    tenant_obj: Optional[Tenant] = None
    x_widget_key = request.headers.get("x-widget-key")
    if x_widget_key:
        try:
            tenant_id = resolve_embed_tenant_id(x_widget_key)
            with SessionLocal() as db:
                tenant_obj = db.get(Tenant, uuid.UUID(tenant_id))
        except Exception:
            tenant_obj = None

    if tenant_obj is None:
        tenant_id = request.query_params.get("tenant_id")
        if tenant_id:
            try:
                with SessionLocal() as db:
                    tenant_obj = db.get(Tenant, uuid.UUID(tenant_id))
            except Exception:
                tenant_obj = None

    if tenant_obj is None and not is_public_api:
        authz = request.headers.get("authorization", "")
        if authz.lower().startswith("bearer "):
            token = authz.split(" ", 1)[1]
            try:
                claims = decode_token(token)
                claim_tenant_ids = claims.get("tenant_ids") or []
                fallback_tenant_id = claims.get("tenant_id") or (claim_tenant_ids[0] if claim_tenant_ids else None)
                if fallback_tenant_id:
                    with SessionLocal() as db:
                        tenant_obj = db.get(Tenant, uuid.UUID(fallback_tenant_id))
            except Exception:
                tenant_obj = None

    if tenant_obj and not tenant_origin_allowed(tenant_obj, effective_origin):
        return JSONResponse(status_code=403, content={"detail": "Origin not allowed for tenant"})
    return await call_next(request)
