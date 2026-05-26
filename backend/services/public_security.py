import ipaddress
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

import geoip2.database
from fastapi import HTTPException, Request
from geoip2.errors import AddressNotFoundError
from sqlalchemy import func, select

from core.middleware import effective_widget_origin, origin_allowed, tenant_origin_allowed
from models import (
    ChatMessage,
    ChatSession,
    SenderType,
    Tenant,
    TenantBlockedCountry,
    TenantBlockedIP,
)

__all__ = [
    "effective_widget_origin",
    "enforce_public_security_and_quota",
    "extract_client_ip",
    "origin_allowed",
    "resolve_country_code_from_ip",
    "tenant_origin_allowed",
    "utc_month_bounds",
]


def extract_client_ip(request: Optional[Request]) -> Optional[str]:
    if request is None:
        return None
    forwarded_for = request.headers.get("x-forwarded-for", "")
    if forwarded_for:
        candidate = forwarded_for.split(",")[0].strip()
        try:
            return str(ipaddress.ip_address(candidate))
        except Exception:
            pass
    if request.client and request.client.host:
        try:
            return str(ipaddress.ip_address(request.client.host))
        except Exception:
            return request.client.host
    return None


def resolve_country_code_from_ip(ip_address: Optional[str]) -> Optional[str]:
    if not ip_address:
        return None
    db_path = os.getenv("GEOIP_DB_PATH", "").strip()
    if not db_path or not os.path.exists(db_path):
        return None
    try:
        with geoip2.database.Reader(db_path) as reader:
            response = reader.country(ip_address)
            code = (response.country.iso_code or "").upper()
            return code or None
    except AddressNotFoundError:
        return None
    except Exception:
        return None


def utc_month_bounds(now_utc: Optional[datetime] = None) -> tuple[datetime, datetime]:
    now_utc = now_utc or datetime.now(timezone.utc)
    start = now_utc.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


def enforce_public_security_and_quota(
    *,
    db,
    tenant_id: str,
    request_obj: Optional[Request],
    apply_ip_country_blocks: bool = True,
    apply_message_quota: bool = True,
):
    """Enforce tenant blocks and/or monthly visitor message quota for public widget traffic."""
    tenant = db.get(Tenant, uuid.UUID(tenant_id))
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    if apply_ip_country_blocks:
        client_ip = extract_client_ip(request_obj)
        if client_ip:
            blocked_ip = db.execute(
                select(TenantBlockedIP).where(
                    TenantBlockedIP.tenant_id == tenant.id,
                    TenantBlockedIP.ip_address == client_ip,
                )
            ).scalar_one_or_none()
            if blocked_ip:
                raise HTTPException(status_code=403, detail="Access blocked for this IP")

        country_code = resolve_country_code_from_ip(client_ip)
        if country_code:
            blocked_country = db.execute(
                select(TenantBlockedCountry).where(
                    TenantBlockedCountry.tenant_id == tenant.id,
                    TenantBlockedCountry.country_code == country_code,
                )
            ).scalar_one_or_none()
            if blocked_country:
                raise HTTPException(status_code=403, detail=f"Access blocked for country: {country_code}")

    if apply_message_quota:
        start_utc, end_utc = utc_month_bounds()
        monthly_messages = db.execute(
            select(func.count(ChatMessage.id))
            .join(ChatSession, ChatSession.id == ChatMessage.session_id)
            .where(
                ChatMessage.tenant_id == tenant.id,
                ChatMessage.sender_type == SenderType.user,
                ChatSession.visitor_id.is_not(None),
                ChatMessage.created_at >= start_utc,
                ChatMessage.created_at < end_utc,
            )
        ).scalar_one()
        if monthly_messages >= (tenant.monthly_message_limit or 15000):
            raise HTTPException(
                status_code=429,
                detail="tenant_message_quota_exceeded",
                headers={
                    "X-Quota-Exceeded": "true",
                    "X-Quota-Message": tenant.quota_reached_message,
                },
            )
