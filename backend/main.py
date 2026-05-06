import asyncio
import json
import logging
import os
import ipaddress
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import unquote, urlparse

import openai
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr
from qdrant_client import QdrantClient
from qdrant_client.http import models
from qdrant_client.http.models import Distance, VectorParams
from sqlalchemy import func, select
import geoip2.database
from geoip2.errors import AddressNotFoundError

from auth import create_access_token, decode_token, hash_password, verify_password
from core.policies import (
    get_accessible_tenant_ids,
    require_role as policy_require_role,
    resolve_effective_tenant_id_for_admin_views,
)
from db import SessionLocal
from embedder import Embedder, LEGACY_VECTOR_PRIMARY_SOURCE_LABEL, LEGACY_VECTOR_PRIMARY_SOURCE_TYPE
from fuzzy_matcher import get_tenant_quick_reply, normalize_trigger_phrase, seed_quick_replies_for_tenant
from integrations.openai_client import OpenAIClientAdapter
from integrations.vector_store import VectorStoreAdapter
from models import (
    AuditLog,
    BlockWordMatchMode,
    ChatMessage,
    ChatSession,
    ChatVisitor,
    FeedbackVote,
    MessageFeedback,
    ReindexJob,
    ReindexScope,
    SessionExperienceRating,
    SenderType,
    Tenant,
    TenantBlockWord,
    TenantBlockWordCategory,
    TenantQuickReply,
    TenantBlockedCountry,
    TenantBlockedIP,
    UsageEvent,
    UsageType,
    User,
    UserRole,
    UserTenant,
)
from url_utils import validate_and_fix_url, get_base_url
from tenant_assets import ensure_tenant_assets_dir, next_avatar_filename, remove_local_avatar_files_for_tenant, tenant_assets_dir

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
logger = logging.getLogger("chatbot-api")

app = FastAPI(title="Multi-Tenant Chatbot API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

openai.api_key = os.getenv("OPENAI_API_KEY")
qdrant_client = None
openai_adapter = OpenAIClientAdapter()


@app.on_event("startup")
async def startup_event():
    global qdrant_client
    try:
        qdrant_client = _initialize_qdrant_client_with_retries()
    except Exception:
        qdrant_client = None
    geo_path = os.getenv("GEOIP_DB_PATH", "").strip()
    if not geo_path:
        logger.warning(
            "GEOIP_DB_PATH is not set; country-based blocking cannot resolve client country "
            "(exact IP blocks still apply)."
        )
    elif not os.path.exists(geo_path):
        logger.warning(
            "GEOIP_DB_PATH points to a missing file (%s); country-based blocking disabled.",
            geo_path,
        )
    else:
        logger.info("Country geolocation enabled (GEOIP_DB_PATH=%s)", geo_path)
        if "dbip" in os.path.basename(geo_path).lower():
            logger.info(
                "DB-IP dataset detected: CC-BY 4.0 may require attribution where results are shown "
                "(see https://db-ip.com/db/ip-to-country-lite)."
            )


class AuthRequest(BaseModel):
    email: EmailStr
    password: str


class AuthResponse(BaseModel):
    access_token: str
    role: str
    tenant_id: Optional[str] = None
    tenant_ids: List[str] = []


class SearchResult(BaseModel):
    content: str
    source: str
    url: str
    score: float


class ChatRequest(BaseModel):
    message: str
    max_results: int = 3
    session_id: str | None = None  # Add session_id to ChatRequest


class ChatResponse(BaseModel):
    response: str
    session_id: str
    message_id: str
    source: Optional[str] = None
    confidence: Optional[float] = None
    sources: Optional[List[SearchResult]] = None


class PublicVisitorProfileRequest(BaseModel):
    visitor_id: str
    name: str
    email: EmailStr


class FeedbackRequest(BaseModel):
    vote: FeedbackVote
    reason: Optional[str] = ""


class ReindexRequest(BaseModel):
    tenant_id: Optional[str] = None


class AdminCreateRequest(BaseModel):
    email: EmailStr
    password: str
    tenant_id: Optional[str] = None
    new_tenant_name: Optional[str] = None
    role: Optional[str] = UserRole.admin.value


class UserStatusRequest(BaseModel):
    is_active: bool


class ResetPasswordRequest(BaseModel):
    new_password: str


class UserTenantAssignRequest(BaseModel):
    tenant_id: str


class UserTenantSetRequest(BaseModel):
    tenant_ids: list[str]


class TenantCreateRequest(BaseModel):
    name: str


class TenantSourceConfigRequest(BaseModel):
    source_db_url: Optional[str] = None
    source_db_type: Optional[str] = None
    source_table_prefix: Optional[str] = None
    source_url_table: Optional[str] = None
    source_mode: Optional[str] = None
    source_static_urls_json: Optional[str] = None
    source_domain_aliases: Optional[str] = None
    source_canonical_base_url: Optional[str] = None


class TenantQuotaConfigRequest(BaseModel):
    monthly_message_limit: Optional[int] = None
    quota_reached_message: Optional[str] = None


class BlockedIPRequest(BaseModel):
    ip_address: str
    reason: Optional[str] = ""


class BlockedCountryRequest(BaseModel):
    country_code: str
    reason: Optional[str] = ""


class TenantBrandingConfigRequest(BaseModel):
    brand_name: Optional[str] = None
    widget_primary_color: Optional[str] = None
    widget_website_url: Optional[str] = None
    widget_source_type: Optional[str] = None
    widget_user_message_color: Optional[str] = None
    widget_bot_message_color: Optional[str] = None
    widget_user_message_text_color: Optional[str] = None
    widget_bot_message_text_color: Optional[str] = None
    widget_header_title: Optional[str] = None
    widget_welcome_message: Optional[str] = None
    privacy_policy_url: Optional[str] = None
    avatar_url: Optional[str] = None
    cors_allowed_origins: Optional[str] = None


class BlockWordCategoryRequest(BaseModel):
    name: str
    match_mode: str
    response_message: str


class BlockWordRequest(BaseModel):
    word: str


class QuickReplyCreateRequest(BaseModel):
    category: str = "general"
    trigger_phrase: str
    response_template: str
    similarity_threshold: Optional[int] = None
    priority: int = 0
    enabled: bool = True


class QuickReplyUpdateRequest(BaseModel):
    category: Optional[str] = None
    trigger_phrase: Optional[str] = None
    response_template: Optional[str] = None
    similarity_threshold: Optional[int] = None
    priority: Optional[int] = None
    enabled: Optional[bool] = None


class TenantIdleRatingConfigRequest(BaseModel):
    idle_rating_wait_seconds: int


class PublicSessionRatingRequest(BaseModel):
    session_id: str
    rating: int


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


def _tenant_collection(tenant_id: str) -> str:
    return f"tenant_{tenant_id}_docs"


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "tenant"


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


def _origin_allowed(origin: Optional[str]) -> bool:
    allowed = os.getenv("WIDGET_ALLOWED_ORIGINS", "*").strip()
    if allowed == "*":
        return True
    allowed_set = {item.strip() for item in allowed.split(",") if item.strip()}
    if not allowed_set:
        return True
    return bool(origin and origin in allowed_set)


def _tenant_origin_allowed(tenant: Optional[Tenant], origin: Optional[str]) -> bool:
    if tenant and tenant.cors_allowed_origins:
        allowed = {item.strip() for item in tenant.cors_allowed_origins.split(",") if item.strip()}
        if "*" in allowed:
            return True
        return bool(origin and origin in allowed)
    return _origin_allowed(origin)


def _extract_client_ip(request: Optional[Request]) -> Optional[str]:
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


def _resolve_country_code_from_ip(ip_address: Optional[str]) -> Optional[str]:
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


def _utc_month_bounds(now_utc: Optional[datetime] = None) -> tuple[datetime, datetime]:
    now_utc = now_utc or datetime.now(timezone.utc)
    start = now_utc.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


def _enforce_public_security_and_quota(
    *,
    db,
    tenant_id: str,
    request_obj: Optional[Request],
    apply_ip_country_blocks: bool = True,
    apply_message_quota: bool = True,
):
    """Enforce tenant blocks and/or monthly visitor message quota for public widget traffic.

    Bootstrap/readiness endpoints (config, visitor profile, feedback, session rating) should pass
    ``apply_ip_country_blocks=False`` and ``apply_message_quota=False`` so the widget can still
    load branding and complete non-chat flows when quota is exhausted or IP/country is blocked;
    ``POST /api/public/chat`` keeps full enforcement.
    """
    tenant = db.get(Tenant, uuid.UUID(tenant_id))
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    if apply_ip_country_blocks:
        client_ip = _extract_client_ip(request_obj)
        if client_ip:
            blocked_ip = db.execute(
                select(TenantBlockedIP).where(
                    TenantBlockedIP.tenant_id == tenant.id,
                    TenantBlockedIP.ip_address == client_ip,
                )
            ).scalar_one_or_none()
            if blocked_ip:
                raise HTTPException(status_code=403, detail="Access blocked for this IP")

        country_code = _resolve_country_code_from_ip(client_ip)
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
        start_utc, end_utc = _utc_month_bounds()
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
                    "Access-Control-Expose-Headers": "X-Quota-Exceeded, X-Quota-Message",
                },
            )


def _resolve_embed_tenant_id(embed_key: Optional[str]) -> str:
    if not embed_key:
        raise HTTPException(status_code=401, detail="Missing widget key")
    key_map = _load_widget_embed_key_map()
    tenant_id = key_map.get(embed_key)
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Invalid widget key")
    return tenant_id


def _resolve_tenant_actor_user_id(db, tenant_id: str) -> uuid.UUID:
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


def _resolve_effective_tenant_id_for_admin_views(db, user_ctx: dict, tenant_id: Optional[str]) -> str:
    return resolve_effective_tenant_id_for_admin_views(db, user_ctx, tenant_id)


def _normalize_visitor_id(visitor_id: Optional[str]) -> str:
    normalized = (visitor_id or "").strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="visitor_id is required")
    if len(normalized) > 64:
        raise HTTPException(status_code=400, detail="visitor_id is invalid")
    return normalized


def _get_visitor_profile(db, tenant_id: str, visitor_id: str) -> Optional[ChatVisitor]:
    return db.execute(
        select(ChatVisitor).where(
            ChatVisitor.tenant_id == uuid.UUID(tenant_id),
            ChatVisitor.visitor_id == visitor_id,
        )
    ).scalar_one_or_none()


def _normalize_visitor_email(email: str) -> tuple[str, str]:
    trimmed = (email or "").strip()
    if not trimmed:
        raise HTTPException(status_code=400, detail="email is required")
    return trimmed, trimmed.lower()


def _get_visitor_profile_by_email(db, tenant_id: str, email_normalized: str) -> Optional[ChatVisitor]:
    return db.execute(
        select(ChatVisitor)
        .where(
            ChatVisitor.tenant_id == uuid.UUID(tenant_id),
            func.lower(ChatVisitor.email) == email_normalized,
        )
        .order_by(ChatVisitor.updated_at.desc())
    ).scalars().first()


def _normalize_avatar_url_for_widget(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    avatar = value.strip()
    if not avatar:
        return None
    marker = "/api/assets/"
    marker_idx = avatar.find(marker)
    if marker_idx >= 0:
        return avatar[marker_idx:]
    return avatar


def _parse_source_dsn(dsn: Optional[str], table_prefix: Optional[str], url_table: Optional[str]) -> Dict[str, Any]:
    if not dsn:
        return {
            "table_prefix": table_prefix,
            "url_table": url_table,
        }
    parsed = urlparse(dsn)
    host = parsed.hostname or ""
    port = parsed.port or 3306
    db_name = (parsed.path or "").lstrip("/")
    cfg = {
        "host": host,
        "port": int(port),
        "database": db_name,
        "table_prefix": table_prefix,
        "url_table": url_table,
    }
    if parsed.username:
        cfg["user"] = unquote(parsed.username)
    if parsed.password:
        cfg["password"] = unquote(parsed.password)
    return cfg


def _is_http_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


def _canonicalize_source_url(url: str, domain_aliases: Optional[List[str]] = None, canonical_base: Optional[str] = None) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return ""
    query_pairs = []
    for pair in (parsed.query or "").split("&"):
        if not pair:
            continue
        key = pair.split("=", 1)[0].strip().lower()
        if key.startswith("utm_") or key in {"gclid", "fbclid", "msclkid"}:
            continue
        query_pairs.append(pair)
    query = "&".join(query_pairs)
    path = parsed.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    hostname = parsed.netloc.lower()
    alias_set = {a.lower() for a in (domain_aliases or []) if a}
    canonical_host = ""
    if canonical_base:
        cb = urlparse(canonical_base)
        canonical_host = (cb.netloc or "").lower()
    if canonical_host and (hostname in alias_set or hostname == canonical_host):
        hostname = canonical_host
    normalized = f"https://{hostname}{path}"
    if query:
        normalized = f"{normalized}?{query}"
    return normalized


def _normalize_source_static_urls_json(
    raw_value: Optional[str],
    domain_aliases: Optional[List[str]] = None,
    canonical_base: Optional[str] = None,
) -> Optional[str]:
    if raw_value is None:
        return None
    text = raw_value.strip()
    if not text:
        return None
    urls: List[str] = []
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            urls = [str(v).strip() for v in parsed]
    except Exception:
        urls = [line.strip() for line in text.splitlines() if line.strip()]
    if not urls:
        return None
    deny_fragments = ("/wp-admin", "/wp-login.php", "/xmlrpc.php")
    normalized = []
    seen = set()
    for url in urls:
        cu = _canonicalize_source_url(url, domain_aliases=domain_aliases, canonical_base=canonical_base)
        if not cu:
            continue
        if any(fragment in cu for fragment in deny_fragments):
            continue
        if cu in seen:
            continue
        seen.add(cu)
        normalized.append(cu)
    return json.dumps(normalized)


def _initialize_qdrant_client_with_retries(max_retries: int = 10, retry_delay: float = 2.0):
    qdrant_host = os.getenv("QDRANT_HOST", "qdrant")
    qdrant_port = int(os.getenv("QDRANT_PORT", "6333"))
    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            client = QdrantClient(host=qdrant_host, port=qdrant_port)
            client.get_collections()
            return client
        except Exception as exc:
            last_error = exc
            time.sleep(retry_delay)
    raise last_error


def ensure_collection_for_tenant(tenant_id: str):
    if qdrant_client is None:
        return
    collection_name = _tenant_collection(tenant_id)
    collection_names = [c.name for c in qdrant_client.get_collections().collections]
    if collection_name not in collection_names:
        qdrant_client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=1536, distance=Distance.COSINE),
        )
        qdrant_client.create_payload_index(
            collection_name=collection_name,
            field_name="source_type",
            field_schema=models.PayloadSchemaType.KEYWORD,
        )

# Helper function to generate embeddings
async def generate_embedding(text: str) -> tuple[List[float], Dict[str, Any]]:
    try:
        response = openai_adapter.create_embedding(model="text-embedding-3-small", input_text=text)
        usage = response.usage or {}
        return response.data[0].embedding, {
            "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
            "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
            "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
            "model_name": "text-embedding-3-small",
        }
    except Exception as e:
        logger.error(f"Error generating embedding: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate embedding")

async def search_qdrant(
    tenant_id: str,
    embedding: List[float],
    limit: int = 5,
    primary_source_type: Optional[str] = None,
) -> List[Any]:
    if qdrant_client is None:
        raise HTTPException(status_code=503, detail="Qdrant service is unavailable")
    collection_name = _tenant_collection(tenant_id)
    primary_st = (primary_source_type or "").strip() or "mrnwebdesigns_ie"

    try:
        vector_store = VectorStoreAdapter(qdrant_client)
        # Primary bucket: tenant-configured Qdrant payload `source_type` (default legacy keyword).
        # Do not set Qdrant score_threshold here: cosine scores for good hits are often ~0.5–0.6
        # (see docs/migraine-reference/main.py search_qdrant). Chat still filters by score >= 0.3 below.
        primary_bucket_results = vector_store.search(
            collection_name=collection_name,
            query_vector=embedding,
            limit=limit,
            source_type=primary_st,
        )

        logger.info("Found %s primary-source (%s) results", len(primary_bucket_results), primary_st)

        # If we don't have enough high-confidence primary-bucket hits, blend external sources
        if len(primary_bucket_results) < limit or max([r.score for r in primary_bucket_results] + [0]) < 0.7:
            external_results = vector_store.search(
                collection_name=collection_name,
                query_vector=embedding,
                source_type="external",
                limit=limit,
            )

            all_results = primary_bucket_results + external_results
            all_results.sort(key=lambda x: x.score, reverse=True)
            logger.info(f"Added {len(external_results)} external results, total: {len(all_results)}")
            return all_results[:limit]

        return primary_bucket_results
    except Exception as e:
        logger.error(f"Error searching Qdrant: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to search knowledge base: {e}")

# Helper function to truncate text for context
def truncate_text_for_context(text, max_chars=3000):
    """Truncate text to fit within context window, preserving beginning and end"""
    if len(text) <= max_chars:
        return text
    
    # Take 80% from beginning, 20% from end
    begin_portion = int(max_chars * 0.8)
    end_portion = max_chars - begin_portion
    return text[:begin_portion] + "\n...[content truncated]...\n" + text[-end_portion:]

def _tenant_chat_brand_label(tenant_row: Optional[Tenant]) -> str:
    if not tenant_row:
        return "MRN Web Designs"
    name = (tenant_row.brand_name or tenant_row.name or "").strip()
    return name or "this organisation"


def _build_chat_system_prompt(tenant_row: Optional[Tenant]) -> str:
    """Tenant-aware system prompt for final answer generation (replaces single-tenant MRN-only copy)."""
    brand = _tenant_chat_brand_label(tenant_row)
    site = (tenant_row.widget_website_url or "").strip() if tenant_row else ""
    site_clause = (
        f" Official website (for grounding references only): {site}."
        if site
        else ""
    )
    return (
        f"You are a helpful assistant for {brand}. Use only the provided context snippets to answer; "
        f"if the context does not contain the answer, say so briefly and suggest checking the website or contacting the team."
        f"{site_clause} "
        "Keep responses concise and under 250 characters when a short reply suffices."
    )


async def preprocess_query(
    original_query: str,
    *,
    tenant_brand_name: str = "MRN Web Designs",
    tenant_website_url: Optional[str] = None,
) -> str:
    """
    Use OpenAI to normalize and enhance queries for better search results.
    Replaces pronouns with the tenant brand label (defaults to legacy MRN when unset).
    """
    site_hint = ""
    if tenant_website_url:
        site_hint = f"\nThe organisation's public website is {tenant_website_url} (use only when relevant to the query).\n"
    system_rules = f"""You are a query preprocessor for a chatbot about {tenant_brand_name}. Your job is to normalize and enhance user queries to make them more searchable in a knowledge base.
{site_hint}
Rules:
1. Replace pronouns like "your", "you", "yours" with "{tenant_brand_name}"
2. Add relevant keywords that would help find information
3. Expand abbreviations and make queries more specific
4. Keep the original intent and meaning
5. Output only the enhanced query, nothing else

Examples (replace entity name consistently with {tenant_brand_name}):
- "your office address" → "{tenant_brand_name} office address location contact information"
- "what services do you offer" → "{tenant_brand_name} services offerings capabilities"
- "your pricing" → "{tenant_brand_name} pricing cost packages"
- "your phone number" → "{tenant_brand_name} phone number contact telephone"
"""
    try:
        response = openai_adapter.create_chat_completion(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": system_rules},
                {"role": "user", "content": f"Original query: {original_query}"},
            ],
            max_tokens=100,
            temperature=0.1,
        )

        enhanced_query = response.choices[0].message.content.strip()
        logger.info(f"Query enhanced: '{original_query}' → '{enhanced_query}'")
        return enhanced_query

    except Exception as e:
        logger.warning(f"Query preprocessing failed: {e}. Using original query.")
        return original_query

_DEFAULT_GENERATE_ANSWER_SYSTEM_PROMPT = (
    "You are a helpful assistant specialized in web design and digital marketing. Your role is to format information "
    "found in the context to provide accurate, helpful, and professional information about website design, development, "
    "maintenance, SEO, paid search, and social media marketing. Present this information as if it's directly from "
    "MRN Web Designs, a custom web design and digital marketing agency. Focus on helping businesses stand out from the "
    "competition by creating digital experiences that boost visibility and drive engagement. Always emphasize custom "
    "solutions over templates or cookie-cutter approaches. IMPORTANT: Keep your responses concise and under 250 "
    "characters to ensure clarity and readability."
)


async def generate_answer(
    query: str,
    context_texts: List[str],
    *,
    system_prompt: Optional[str] = None,
) -> tuple[str, Dict[str, Any]]:
    try:
        # Set a maximum total context length (in chars) to prevent errors
        max_total_context = 14000  # Safe limit for gpt-3.5-turbo (16k tokens)

        # Truncate each context text
        truncated_texts = []
        total_chars = 0
        max_chars_per_source = max_total_context // max(len(context_texts), 1)

        for text in context_texts:
            # Limit each source text proportionally
            truncated = truncate_text_for_context(text, max_chars_per_source)
            truncated_texts.append(truncated)
            total_chars += len(truncated)

        # If still too large, reduce even more
        if total_chars > max_total_context:
            # Calculate reduction factor
            reduction_factor = max_total_context / total_chars

            truncated_texts = []
            for text in context_texts:
                # Adjust max chars based on reduction factor
                adjusted_max = int(max_chars_per_source * reduction_factor)
                truncated = truncate_text_for_context(text, max(adjusted_max, 500))
                truncated_texts.append(truncated)

        # Join the truncated texts
        context = "\n\n---\n\n".join(truncated_texts)
        logger.info(f"Total context length (chars): {len(context)}")

        sys_msg = system_prompt or _DEFAULT_GENERATE_ANSWER_SYSTEM_PROMPT
        response = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": sys_msg},
                {"role": "user", "content": f"Question: {query}\n\nContext: {context}"},
            ],
        )
        
        usage = response.usage or {}
        return response.choices[0].message.content, {
            "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
            "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
            "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
            "model_name": "gpt-3.5-turbo",
        }
    except Exception as e:
        logger.error(f"Error generating answer: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate answer")


def _record_usage_event(
    db,
    *,
    tenant_id: uuid.UUID,
    usage_type: UsageType,
    model_name: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    session_id: Optional[uuid.UUID] = None,
    message_id: Optional[uuid.UUID] = None,
    meta_json: Optional[dict] = None,
):
    db.add(
        UsageEvent(
            tenant_id=tenant_id,
            session_id=session_id,
            message_id=message_id,
            usage_type=usage_type,
            model_name=model_name or "",
            prompt_tokens=int(prompt_tokens or 0),
            completion_tokens=int(completion_tokens or 0),
            total_tokens=int(total_tokens or 0),
            meta_json=meta_json or {},
        )
    )


def _ensure_manage_tenant(db, user_ctx: dict, tenant_id: str, allow_admin: bool = True):
    allowed_roles = [UserRole.superadmin.value, UserRole.admin.value, UserRole.manager.value] if allow_admin else [UserRole.superadmin.value]
    require_role(user_ctx, allowed_roles)
    if user_ctx["role"] != UserRole.superadmin.value and tenant_id not in get_accessible_tenant_ids(db, user_ctx):
        raise HTTPException(status_code=403, detail="Forbidden")


def _find_block_word_match(db, tenant_id: str, message: str) -> Optional[dict]:
    categories = db.execute(
        select(TenantBlockWordCategory).where(TenantBlockWordCategory.tenant_id == uuid.UUID(tenant_id))
    ).scalars().all()
    if not categories:
        return None
    normalized_message = (message or "").strip()
    lowered_message = normalized_message.lower()
    for category in categories:
        words = db.execute(
            select(TenantBlockWord).where(TenantBlockWord.category_id == category.id).order_by(TenantBlockWord.created_at.asc())
        ).scalars().all()
        if not words:
            continue
        for item in words:
            candidate = (item.word or "").strip()
            if not candidate:
                continue
            mode = str(category.match_mode)
            is_match = False
            if mode == BlockWordMatchMode.exact.value:
                is_match = lowered_message == candidate.lower()
            elif mode == BlockWordMatchMode.substring.value:
                is_match = candidate.lower() in lowered_message
            elif mode == BlockWordMatchMode.regex.value:
                try:
                    is_match = re.search(candidate, normalized_message, flags=re.IGNORECASE) is not None
                except re.error:
                    is_match = False
            if is_match:
                return {
                    "category_id": str(category.id),
                    "category_name": category.name,
                    "match_mode": mode,
                    "matched_word": candidate,
                    "response_message": category.response_message,
                }
    return None


async def _run_chat_for_tenant(
    request: ChatRequest,
    tenant_id: str,
    actor_user_id: uuid.UUID,
    db,
    is_public_chat: bool = False,
    public_visitor: Optional[ChatVisitor] = None,
) -> Dict[str, Any]:
    ensure_collection_for_tenant(tenant_id)
    tenant_row = db.get(Tenant, uuid.UUID(tenant_id))
    vector_primary_source_type = tenant_row.widget_source_type if tenant_row else None
    url_fallback = ((tenant_row.widget_website_url or "").strip() or None) if tenant_row else None

    if request.session_id:
        session = db.get(ChatSession, uuid.UUID(request.session_id))
        if not session or str(session.tenant_id) != tenant_id:
            raise HTTPException(status_code=404, detail="Session not found")
    else:
        session = ChatSession(tenant_id=uuid.UUID(tenant_id), created_by_user_id=actor_user_id)
        db.add(session)
        db.flush()
        if is_public_chat:
            if not public_visitor:
                raise HTTPException(status_code=428, detail="Public visitor profile is required")
            session.visitor_id = public_visitor.visitor_id
            session.visitor_name = public_visitor.name
            session.visitor_email = public_visitor.email
            session.title = f"{public_visitor.name} ({public_visitor.email})"

    db.add(
        ChatMessage(
            session_id=session.id,
            tenant_id=session.tenant_id,
            sender_type=SenderType.user,
            content=request.message,
            model_name="",
        )
    )

    if is_public_chat:
        block_match = _find_block_word_match(db, tenant_id, request.message)
        if block_match:
            session.block_triggered = True
            session.last_message_at = datetime.utcnow()
            blocked_response = ChatMessage(
                session_id=session.id,
                tenant_id=session.tenant_id,
                sender_type=SenderType.assistant,
                content=block_match["response_message"],
                model_name="block-word-policy",
                token_usage_json={"policy_blocked": True},
            )
            db.add(blocked_response)
            db.add(
                AuditLog(
                    actor_user_id=actor_user_id,
                    actor_role="public",
                    tenant_id=session.tenant_id,
                    action="tenant_block_word_triggered",
                    target_type="tenant_block_word_category",
                    target_id=block_match["category_id"],
                    details_json={
                        "category_name": block_match["category_name"],
                        "match_mode": block_match["match_mode"],
                        "matched_word": block_match["matched_word"],
                        "session_id": str(session.id),
                    },
                )
            )
            db.commit()
            return {
                "response": block_match["response_message"],
                "session_id": str(session.id),
                "message_id": str(blocked_response.id),
                "source": "block_word",
                "confidence": 1.0,
                "sources": [],
            }

    fuzzy_response = get_tenant_quick_reply(db, tenant_id, request.message, tenant_row)
    if fuzzy_response:
        answer = fuzzy_response["response"]
        sources = fuzzy_response.get("sources", [])
        confidence = fuzzy_response.get("confidence", 1.0)
        source_type = "fuzzy"
        completion_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "model_name": "fuzzy-match"}
    else:
        if qdrant_client is None:
            raise HTTPException(status_code=503, detail="Qdrant unavailable")
        enhanced_query = await preprocess_query(
            request.message,
            tenant_brand_name=_tenant_chat_brand_label(tenant_row),
            tenant_website_url=((tenant_row.widget_website_url or "").strip() or None) if tenant_row else None,
        )
        embedding, embedding_usage = await generate_embedding(enhanced_query)
        _record_usage_event(
            db,
            tenant_id=session.tenant_id,
            usage_type=UsageType.chat_embedding,
            model_name=embedding_usage.get("model_name", ""),
            prompt_tokens=embedding_usage.get("prompt_tokens", 0),
            completion_tokens=embedding_usage.get("completion_tokens", 0),
            total_tokens=embedding_usage.get("total_tokens", 0),
            session_id=session.id,
            meta_json={"source": "chat_query"},
        )
        search_results = await search_qdrant(
            tenant_id,
            embedding,
            request.max_results,
            primary_source_type=vector_primary_source_type,
        )
        filtered_results = [result for result in search_results if result.score >= 0.3]
        context_texts: list[str] = []
        sources: list[SearchResult] = []
        for result in filtered_results:
            original_url = result.payload["url"]
            validated_url = validate_and_fix_url(original_url, fallback_base=url_fallback) or get_base_url(original_url)
            if not validated_url:
                continue
            context_texts.append(f"Source: {result.payload['source']}\nURL: {validated_url}\n{result.payload['content']}")
            sources.append(
                SearchResult(
                    content=result.payload["content"][:200] + "...",
                    source=result.payload["source"],
                    url=validated_url,
                    score=result.score,
                )
            )
        if not sources:
            answer = "I could not find high-confidence context for that request."
            confidence = 0.0
            completion_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "model_name": "gpt-3.5-turbo"}
        else:
            answer, completion_usage = await generate_answer(
                request.message,
                context_texts,
                system_prompt=_build_chat_system_prompt(tenant_row),
            )
            confidence = filtered_results[0].score
        source_type = "vector_search"

    assistant_message = ChatMessage(
        session_id=session.id,
        tenant_id=session.tenant_id,
        sender_type=SenderType.assistant,
        content=answer,
        model_name="gpt-3.5-turbo",
        token_usage_json={
            "completion_tokens": completion_usage.get("completion_tokens", 0),
            "prompt_tokens": completion_usage.get("prompt_tokens", 0),
            "total_tokens": completion_usage.get("total_tokens", 0),
            "model_name": completion_usage.get("model_name", "gpt-3.5-turbo"),
        },
    )
    db.add(assistant_message)
    db.flush()
    _record_usage_event(
        db,
        tenant_id=session.tenant_id,
        usage_type=UsageType.chat_completion,
        model_name=completion_usage.get("model_name", "gpt-3.5-turbo"),
        prompt_tokens=completion_usage.get("prompt_tokens", 0),
        completion_tokens=completion_usage.get("completion_tokens", 0),
        total_tokens=completion_usage.get("total_tokens", 0),
        session_id=session.id,
        message_id=assistant_message.id,
        meta_json={"source": source_type},
    )
    session.last_message_at = datetime.now(timezone.utc)
    db.commit()
    return ChatResponse(
        response=answer,
        session_id=str(session.id),
        message_id=str(assistant_message.id),
        source=source_type,
        confidence=confidence,
        sources=sources,
    )

@app.post("/api/auth/register", response_model=AuthResponse)
async def register(payload: AuthRequest, db=Depends(db_session)):
    existing = db.execute(select(User).where(User.email == payload.email)).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail="Email already in use")
    tenant = Tenant(name=f"{payload.email} tenant", slug=str(uuid.uuid4()), status="active")
    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        role=UserRole.admin,
        is_active=True,
    )
    db.add(tenant)
    db.add(user)
    db.flush()
    db.add(UserTenant(user_id=user.id, tenant_id=tenant.id, membership_role="owner"))
    seed_quick_replies_for_tenant(db, tenant.id)
    db.commit()
    ensure_collection_for_tenant(str(tenant.id))
    token = create_access_token(str(user.id), user.role.value, str(tenant.id))
    return AuthResponse(access_token=token, role=user.role.value, tenant_id=str(tenant.id), tenant_ids=[str(tenant.id)])


@app.post("/api/auth/login", response_model=AuthResponse)
async def login(payload: AuthRequest, db=Depends(db_session)):
    user = db.execute(select(User).where(User.email == payload.email)).scalar_one_or_none()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    tenant_links = db.execute(select(UserTenant).where(UserTenant.user_id == user.id).order_by(UserTenant.created_at.asc())).scalars().all()
    tenant_ids = [str(link.tenant_id) for link in tenant_links]
    tenant_id = tenant_ids[0] if tenant_ids else None
    token = create_access_token(str(user.id), user.role.value, tenant_id)
    return AuthResponse(access_token=token, role=user.role.value, tenant_id=tenant_id, tenant_ids=tenant_ids)


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, user_ctx=Depends(get_current_user), db=Depends(db_session)) -> Dict[str, Any]:
    tenant_id = resolve_effective_tenant_id_for_admin_views(db, user_ctx, None)
    if not tenant_id:
        raise HTTPException(status_code=400, detail="Tenant context missing")
    return await _run_chat_for_tenant(request, tenant_id, user_ctx["user"].id, db)


@app.post("/api/public/chat", response_model=ChatResponse)
async def public_chat(
    request: ChatRequest,
    db=Depends(db_session),
    request_obj: Request = None,
    x_widget_key: Optional[str] = Header(default=None, alias="X-Widget-Key"),
    x_visitor_id: Optional[str] = Header(default=None, alias="X-Visitor-Id"),
    origin: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    if os.getenv("WIDGET_REQUIRE_ORIGIN", "false").lower() == "true" and not _origin_allowed(origin):
        raise HTTPException(status_code=403, detail="Origin not allowed for widget")
    tenant_id = _resolve_embed_tenant_id(x_widget_key)
    _enforce_public_security_and_quota(db=db, tenant_id=tenant_id, request_obj=request_obj)
    visitor_id = _normalize_visitor_id(x_visitor_id)
    visitor = _get_visitor_profile(db, tenant_id, visitor_id)
    if not visitor:
        raise HTTPException(status_code=428, detail="Public visitor profile is required")
    actor_user_id = _resolve_tenant_actor_user_id(db, tenant_id)
    return await _run_chat_for_tenant(
        request,
        tenant_id,
        actor_user_id,
        db,
        is_public_chat=True,
        public_visitor=visitor,
    )


@app.get("/api/public/visitor-profile")
async def get_public_visitor_profile(
    db=Depends(db_session),
    request_obj: Request = None,
    x_widget_key: Optional[str] = Header(default=None, alias="X-Widget-Key"),
    x_visitor_id: Optional[str] = Header(default=None, alias="X-Visitor-Id"),
    origin: Optional[str] = Header(default=None),
):
    if os.getenv("WIDGET_REQUIRE_ORIGIN", "false").lower() == "true" and not _origin_allowed(origin):
        raise HTTPException(status_code=403, detail="Origin not allowed for widget")
    tenant_id = _resolve_embed_tenant_id(x_widget_key)
    _enforce_public_security_and_quota(
        db=db,
        tenant_id=tenant_id,
        request_obj=request_obj,
        apply_ip_country_blocks=False,
        apply_message_quota=False,
    )
    visitor_id = _normalize_visitor_id(x_visitor_id)
    visitor = _get_visitor_profile(db, tenant_id, visitor_id)
    return {"profile_exists": bool(visitor)}


@app.get("/api/public/config")
async def get_public_widget_config(
    request_obj: Request,
    db=Depends(db_session),
    x_widget_key: Optional[str] = Header(default=None, alias="X-Widget-Key"),
    origin: Optional[str] = Header(default=None),
):
    tenant_id = _resolve_embed_tenant_id(x_widget_key)
    tenant = db.get(Tenant, uuid.UUID(tenant_id))
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if not _tenant_origin_allowed(tenant, origin):
        raise HTTPException(status_code=403, detail="Origin not allowed for widget")
    _enforce_public_security_and_quota(
        db=db,
        tenant_id=tenant_id,
        request_obj=request_obj,
        apply_ip_country_blocks=False,
        apply_message_quota=False,
    )
    return {
        "tenant_id": tenant_id,
        "brand_name": tenant.brand_name,
        "primary_color": tenant.widget_primary_color,
        "website_url": tenant.widget_website_url,
        "source_type": tenant.widget_source_type,
        "user_message_color": tenant.widget_user_message_color,
        "bot_message_color": tenant.widget_bot_message_color,
        "user_message_text_color": tenant.widget_user_message_text_color,
        "bot_message_text_color": tenant.widget_bot_message_text_color,
        "header_title": tenant.widget_header_title,
        "welcome_message": tenant.widget_welcome_message,
        "avatar_url": _normalize_avatar_url_for_widget(tenant.avatar_url),
        "privacy_policy_url": tenant.privacy_policy_url,
        "idle_rating_wait_seconds": tenant.idle_rating_wait_seconds,
    }


@app.post("/api/public/visitor-profile")
async def upsert_public_visitor_profile(
    payload: PublicVisitorProfileRequest,
    db=Depends(db_session),
    request_obj: Request = None,
    x_widget_key: Optional[str] = Header(default=None, alias="X-Widget-Key"),
    origin: Optional[str] = Header(default=None),
):
    if os.getenv("WIDGET_REQUIRE_ORIGIN", "false").lower() == "true" and not _origin_allowed(origin):
        raise HTTPException(status_code=403, detail="Origin not allowed for widget")
    tenant_id = _resolve_embed_tenant_id(x_widget_key)
    _enforce_public_security_and_quota(
        db=db,
        tenant_id=tenant_id,
        request_obj=request_obj,
        apply_ip_country_blocks=False,
        apply_message_quota=False,
    )
    visitor_id = _normalize_visitor_id(payload.visitor_id)
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    email_trimmed, email_normalized = _normalize_visitor_email(str(payload.email))
    visitor = _get_visitor_profile(db, tenant_id, visitor_id)
    if visitor:
        visitor.name = name
        visitor.email = email_trimmed
        resolved_visitor_id = visitor.visitor_id
    else:
        # Hybrid identity model: device visitor_id remains client-local, while
        # matching email across devices resolves to a canonical visitor profile.
        canonical = _get_visitor_profile_by_email(db, tenant_id, email_normalized)
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

@app.get("/health")
async def health_check():
    return {"status": "healthy", "qdrant": "connected" if qdrant_client else "unavailable"}


@app.post("/api/messages/{message_id}/feedback")
async def add_feedback(message_id: str, payload: FeedbackRequest, user_ctx=Depends(get_current_user), db=Depends(db_session)):
    message = db.get(ChatMessage, uuid.UUID(message_id))
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")
    if user_ctx["role"] != UserRole.superadmin.value and str(message.tenant_id) not in get_accessible_tenant_ids(db, user_ctx):
        raise HTTPException(status_code=403, detail="Forbidden")
    feedback = db.execute(
        select(MessageFeedback).where(
            MessageFeedback.message_id == message.id,
            MessageFeedback.user_id == user_ctx["user"].id,
        )
    ).scalar_one_or_none()
    if feedback:
        feedback.vote = payload.vote
        feedback.reason = payload.reason or ""
    else:
        db.add(
            MessageFeedback(
                tenant_id=message.tenant_id,
                message_id=message.id,
                user_id=user_ctx["user"].id,
                vote=payload.vote,
                reason=payload.reason or "",
            )
        )
    db.commit()
    return {"status": "ok"}


@app.post("/api/public/messages/{message_id}/feedback")
async def add_public_feedback(
    message_id: str,
    payload: FeedbackRequest,
    db=Depends(db_session),
    request_obj: Request = None,
    x_widget_key: Optional[str] = Header(default=None, alias="X-Widget-Key"),
    origin: Optional[str] = Header(default=None),
):
    if os.getenv("WIDGET_REQUIRE_ORIGIN", "false").lower() == "true" and not _origin_allowed(origin):
        raise HTTPException(status_code=403, detail="Origin not allowed for widget")
    tenant_id = _resolve_embed_tenant_id(x_widget_key)
    _enforce_public_security_and_quota(
        db=db,
        tenant_id=tenant_id,
        request_obj=request_obj,
        apply_ip_country_blocks=False,
        apply_message_quota=False,
    )
    message = db.get(ChatMessage, uuid.UUID(message_id))
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")
    if str(message.tenant_id) != tenant_id:
        raise HTTPException(status_code=403, detail="Forbidden")

    # Public feedback is keyed to the tenant actor user backing this chat session.
    session = db.get(ChatSession, message.session_id)
    actor_user_id = session.created_by_user_id if session else _resolve_tenant_actor_user_id(db, tenant_id)
    feedback = db.execute(
        select(MessageFeedback).where(
            MessageFeedback.message_id == message.id,
            MessageFeedback.user_id == actor_user_id,
        )
    ).scalar_one_or_none()
    if feedback:
        feedback.vote = payload.vote
        feedback.reason = payload.reason or ""
    else:
        db.add(
            MessageFeedback(
                tenant_id=message.tenant_id,
                message_id=message.id,
                user_id=actor_user_id,
                vote=payload.vote,
                reason=payload.reason or "",
            )
        )
    db.commit()
    return {"status": "ok"}


@app.get("/api/public/session-rating/{session_id}")
async def get_public_session_rating_status(
    session_id: str,
    db=Depends(db_session),
    request_obj: Request = None,
    x_widget_key: Optional[str] = Header(default=None, alias="X-Widget-Key"),
    x_visitor_id: Optional[str] = Header(default=None, alias="X-Visitor-Id"),
    origin: Optional[str] = Header(default=None),
):
    tenant_id = _resolve_embed_tenant_id(x_widget_key)
    tenant = db.get(Tenant, uuid.UUID(tenant_id))
    if not _tenant_origin_allowed(tenant, origin):
        raise HTTPException(status_code=403, detail="Origin not allowed for widget")
    _enforce_public_security_and_quota(
        db=db,
        tenant_id=tenant_id,
        request_obj=request_obj,
        apply_ip_country_blocks=False,
        apply_message_quota=False,
    )
    _normalize_visitor_id(x_visitor_id)
    session = db.get(ChatSession, uuid.UUID(session_id))
    if not session or str(session.tenant_id) != tenant_id:
        raise HTTPException(status_code=404, detail="Session not found")
    existing = db.execute(
        select(SessionExperienceRating).where(SessionExperienceRating.session_id == session.id)
    ).scalar_one_or_none()
    return {"session_id": session_id, "submitted": bool(existing), "rating": existing.rating if existing else None}


@app.post("/api/public/session-rating")
async def submit_public_session_rating(
    payload: PublicSessionRatingRequest,
    db=Depends(db_session),
    request_obj: Request = None,
    x_widget_key: Optional[str] = Header(default=None, alias="X-Widget-Key"),
    x_visitor_id: Optional[str] = Header(default=None, alias="X-Visitor-Id"),
    origin: Optional[str] = Header(default=None),
):
    tenant_id = _resolve_embed_tenant_id(x_widget_key)
    tenant = db.get(Tenant, uuid.UUID(tenant_id))
    if not _tenant_origin_allowed(tenant, origin):
        raise HTTPException(status_code=403, detail="Origin not allowed for widget")
    _enforce_public_security_and_quota(
        db=db,
        tenant_id=tenant_id,
        request_obj=request_obj,
        apply_ip_country_blocks=False,
        apply_message_quota=False,
    )
    visitor_id = _normalize_visitor_id(x_visitor_id)
    if payload.rating < 1 or payload.rating > 5:
        raise HTTPException(status_code=400, detail="rating must be between 1 and 5")
    session = db.get(ChatSession, uuid.UUID(payload.session_id))
    if not session or str(session.tenant_id) != tenant_id:
        raise HTTPException(status_code=404, detail="Session not found")
    existing = db.execute(
        select(SessionExperienceRating).where(SessionExperienceRating.session_id == session.id)
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="rating_already_submitted")
    db.add(
        SessionExperienceRating(
            tenant_id=session.tenant_id,
            session_id=session.id,
            visitor_id=visitor_id,
            rating=payload.rating,
        )
    )
    db.add(
        AuditLog(
            actor_user_id=session.created_by_user_id,
            actor_role="public",
            tenant_id=session.tenant_id,
            action="session_experience_rating_submitted",
            target_type="chat_session",
            target_id=str(session.id),
            details_json={"rating": payload.rating},
        )
    )
    db.commit()
    return {"status": "ok", "session_id": payload.session_id, "rating": payload.rating}


@app.get("/api/admin/chats")
async def admin_chats(
    user_ctx=Depends(get_current_user),
    db=Depends(db_session),
    q: Optional[str] = Query(default=None),
    tenant_id: Optional[str] = Query(default=None),
    page: int = Query(default=1),
    page_size: int = Query(default=20),
):
    page = max(page, 1)
    page_size = max(1, min(page_size, 100))
    effective_tenant_id = resolve_effective_tenant_id_for_admin_views(db, user_ctx, tenant_id)
    sessions = db.execute(
        select(ChatSession)
        .where(ChatSession.tenant_id == uuid.UUID(effective_tenant_id))
        .order_by(ChatSession.last_message_at.desc())
    ).scalars().all()
    if q:
        q_l = q.lower()
        session_ids = [s.id for s in sessions]
        message_session_ids = set()
        if session_ids:
            message_rows = db.execute(
                select(ChatMessage.session_id).where(ChatMessage.session_id.in_(session_ids), ChatMessage.content.ilike(f"%{q}%"))
            ).all()
            message_session_ids = {row[0] for row in message_rows}
        sessions = [
            s for s in sessions
            if q_l in (s.title or "").lower()
            or q_l in str(s.id)
            or q_l in (s.visitor_name or "").lower()
            or q_l in (s.visitor_email or "").lower()
            or s.id in message_session_ids
        ]
    total = len(sessions)
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    sessions_page = sessions[start_idx:end_idx]
    session_ids = [s.id for s in sessions_page]
    message_count_by_session: Dict[str, int] = {}
    if session_ids:
        count_rows = db.execute(
            select(ChatMessage.session_id, func.count(ChatMessage.id))
            .where(ChatMessage.session_id.in_(session_ids))
            .group_by(ChatMessage.session_id)
        ).all()
        message_count_by_session = {str(sid): int(n) for sid, n in count_rows}
    feedback_by_session = {}
    if session_ids:
        message_rows = db.execute(
            select(ChatMessage.id, ChatMessage.session_id).where(ChatMessage.session_id.in_(session_ids))
        ).all()
        message_to_session = {m_id: s_id for m_id, s_id in message_rows}
        message_ids = list(message_to_session.keys())
        if message_ids:
            feedback_rows = db.execute(select(MessageFeedback.message_id, MessageFeedback.vote).where(MessageFeedback.message_id.in_(message_ids))).all()
            for message_id, vote in feedback_rows:
                session_id = message_to_session.get(message_id)
                if not session_id:
                    continue
                sid = str(session_id)
                if sid not in feedback_by_session:
                    feedback_by_session[sid] = {"up": 0, "down": 0}
                if vote == FeedbackVote.up:
                    feedback_by_session[sid]["up"] += 1
                elif vote == FeedbackVote.down:
                    feedback_by_session[sid]["down"] += 1
    items = [
        {
            "id": str(s.id),
            "tenant_id": str(s.tenant_id),
            "title": s.title,
            "visitor_name": s.visitor_name,
            "visitor_email": s.visitor_email,
            "block_triggered": bool(s.block_triggered),
            "last_message_at": s.last_message_at.isoformat(),
            "feedback_summary": feedback_by_session.get(str(s.id), {"up": 0, "down": 0}),
            "message_count": message_count_by_session.get(str(s.id), 0),
        }
        for s in sessions_page
    ]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@app.get("/api/admin/users")
async def admin_users(
    user_ctx=Depends(get_current_user),
    db=Depends(db_session),
    tenant_id: Optional[str] = Query(default=None),
    page: int = Query(default=1),
    page_size: int = Query(default=20),
):
    page = max(page, 1)
    page_size = max(1, min(page_size, 100))
    effective_tenant_id = resolve_effective_tenant_id_for_admin_views(db, user_ctx, tenant_id)
    tenant_uuid = uuid.UUID(effective_tenant_id)
    user_ids = db.execute(select(UserTenant.user_id).where(UserTenant.tenant_id == tenant_uuid)).scalars().all()
    if user_ids:
        users = db.execute(
            select(User)
            .where(User.id.in_(list(user_ids)))
            .where(User.role != UserRole.superadmin)
            .order_by(User.created_at.desc())
        ).scalars().all()
    else:
        users = []
    total = len(users)
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    users_page = users[start_idx:end_idx]
    items = [
        {
            "id": str(u.id),
            "email": u.email,
            "role": u.role.value,
            "is_active": u.is_active,
            "created_at": u.created_at.isoformat(),
        }
        for u in users_page
    ]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@app.get("/api/admin/users/{user_id}/tenants")
async def admin_user_tenants(user_id: str, user_ctx=Depends(get_current_user), db=Depends(db_session)):
    target_user = db.get(User, uuid.UUID(user_id))
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
    require_role(user_ctx, [UserRole.superadmin.value, UserRole.admin.value])
    if user_ctx["role"] != UserRole.superadmin.value:
        actor_tenants = set(get_accessible_tenant_ids(db, user_ctx))
        if not actor_tenants:
            raise HTTPException(status_code=403, detail="Forbidden")
        memberships = db.execute(select(UserTenant).where(UserTenant.user_id == target_user.id)).scalars().all()
        if not any(str(m.tenant_id) in actor_tenants for m in memberships):
            raise HTTPException(status_code=403, detail="Forbidden")

    memberships = db.execute(select(UserTenant).where(UserTenant.user_id == target_user.id)).scalars().all()
    tenant_map = {str(t.id): t for t in db.execute(select(Tenant).where(Tenant.id.in_([m.tenant_id for m in memberships]))).scalars().all()} if memberships else {}
    items = []
    for m in memberships:
        t = tenant_map.get(str(m.tenant_id))
        items.append(
            {
                "tenant_id": str(m.tenant_id),
                "tenant_name": t.name if t else None,
                "membership_role": m.membership_role,
            }
        )
    return {"user_id": user_id, "items": items}


@app.post("/api/admin/users/{user_id}/tenants")
async def add_admin_user_tenant(
    user_id: str,
    payload: UserTenantAssignRequest,
    user_ctx=Depends(get_current_user),
    db=Depends(db_session),
):
    target_user = db.get(User, uuid.UUID(user_id))
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
    tenant = db.get(Tenant, uuid.UUID(payload.tenant_id))
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    require_role(user_ctx, [UserRole.superadmin.value, UserRole.admin.value])
    if user_ctx["role"] != UserRole.superadmin.value:
        if target_user.role != UserRole.manager:
            raise HTTPException(status_code=403, detail="Admins can only reassign managers")
        actor_tenants = set(get_accessible_tenant_ids(db, user_ctx))
        if str(tenant.id) not in actor_tenants:
            raise HTTPException(status_code=403, detail="Forbidden")

    existing = db.execute(
        select(UserTenant).where(UserTenant.user_id == target_user.id, UserTenant.tenant_id == tenant.id)
    ).scalars().first()
    if existing:
        return {"status": "ok", "tenant_id": str(tenant.id), "already_exists": True}

    if target_user.role == UserRole.manager:
        current = db.execute(select(UserTenant).where(UserTenant.user_id == target_user.id)).scalars().all()
        if current:
            raise HTTPException(status_code=400, detail="Managers can only be assigned to one tenant")

    db.add(UserTenant(user_id=target_user.id, tenant_id=tenant.id, membership_role="admin"))
    db.add(
        AuditLog(
            actor_user_id=user_ctx["user"].id,
            actor_role=user_ctx["role"],
            tenant_id=tenant.id,
            action="user_tenant_added",
            target_type="user_tenant",
            target_id=f"{user_id}:{tenant.id}",
            details_json={"user_id": user_id, "tenant_id": str(tenant.id)},
        )
    )
    db.commit()
    return {"status": "ok", "tenant_id": str(tenant.id)}


@app.delete("/api/admin/users/{user_id}/tenants/{tenant_id}")
async def remove_admin_user_tenant(
    user_id: str,
    tenant_id: str,
    user_ctx=Depends(get_current_user),
    db=Depends(db_session),
):
    target_user = db.get(User, uuid.UUID(user_id))
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
    tenant = db.get(Tenant, uuid.UUID(tenant_id))
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    require_role(user_ctx, [UserRole.superadmin.value, UserRole.admin.value])
    if user_ctx["role"] != UserRole.superadmin.value:
        if target_user.role != UserRole.manager:
            raise HTTPException(status_code=403, detail="Admins can only reassign managers")
        actor_tenants = set(get_accessible_tenant_ids(db, user_ctx))
        if tenant_id not in actor_tenants:
            raise HTTPException(status_code=403, detail="Forbidden")

    link = db.execute(select(UserTenant).where(UserTenant.user_id == target_user.id, UserTenant.tenant_id == tenant.id)).scalars().first()
    if not link:
        raise HTTPException(status_code=404, detail="User-tenant association not found")

    remaining = db.execute(select(UserTenant).where(UserTenant.user_id == target_user.id)).scalars().all()
    if target_user.role in (UserRole.admin, UserRole.manager) and len(remaining) <= 1:
        raise HTTPException(status_code=400, detail="User must remain associated with at least one tenant")

    db.delete(link)
    db.add(
        AuditLog(
            actor_user_id=user_ctx["user"].id,
            actor_role=user_ctx["role"],
            tenant_id=tenant.id,
            action="user_tenant_removed",
            target_type="user_tenant",
            target_id=f"{user_id}:{tenant_id}",
            details_json={"user_id": user_id, "tenant_id": tenant_id},
        )
    )
    db.commit()
    return {"status": "ok", "tenant_id": tenant_id}


@app.put("/api/admin/users/{user_id}/tenants")
async def set_admin_user_tenants(
    user_id: str,
    payload: UserTenantSetRequest,
    user_ctx=Depends(get_current_user),
    db=Depends(db_session),
):
    target_user = db.get(User, uuid.UUID(user_id))
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
    require_role(user_ctx, [UserRole.superadmin.value, UserRole.admin.value])

    next_ids = list(dict.fromkeys([str(tid) for tid in (payload.tenant_ids or []) if str(tid).strip()]))
    if target_user.role == UserRole.manager and len(next_ids) != 1:
        raise HTTPException(status_code=400, detail="Managers must be assigned to exactly one tenant")
    if target_user.role == UserRole.admin and len(next_ids) < 1:
        raise HTTPException(status_code=400, detail="Admin must remain associated with at least one tenant")
    if target_user.role == UserRole.superadmin:
        raise HTTPException(status_code=400, detail="Superadmin associations are managed by role")

    next_uuids = []
    for tid in next_ids:
        tenant = db.get(Tenant, uuid.UUID(tid))
        if not tenant:
            raise HTTPException(status_code=404, detail=f"Tenant not found: {tid}")
        next_uuids.append(tenant.id)

    if user_ctx["role"] != UserRole.superadmin.value:
        actor_tenants = set(get_accessible_tenant_ids(db, user_ctx))
        if not actor_tenants:
            raise HTTPException(status_code=403, detail="Forbidden")
        current_links = db.execute(select(UserTenant).where(UserTenant.user_id == target_user.id)).scalars().all()
        if not any(str(m.tenant_id) in actor_tenants for m in current_links):
            raise HTTPException(status_code=403, detail="Forbidden")
        if target_user.role != UserRole.manager:
            raise HTTPException(status_code=403, detail="Admins can only reassign managers")
        if not all(str(tid) in actor_tenants for tid in next_ids):
            raise HTTPException(status_code=403, detail="Forbidden")

    current_links = db.execute(select(UserTenant).where(UserTenant.user_id == target_user.id)).scalars().all()
    current_set = {str(m.tenant_id) for m in current_links}
    next_set = set(next_ids)

    for m in current_links:
        if str(m.tenant_id) not in next_set:
            db.delete(m)
            db.add(
                AuditLog(
                    actor_user_id=user_ctx["user"].id,
                    actor_role=user_ctx["role"],
                    tenant_id=m.tenant_id,
                    action="user_tenant_removed",
                    target_type="user_tenant",
                    target_id=f"{user_id}:{m.tenant_id}",
                    details_json={"user_id": user_id, "tenant_id": str(m.tenant_id)},
                )
            )

    for tid in next_set:
        if tid not in current_set:
            db.add(UserTenant(user_id=target_user.id, tenant_id=uuid.UUID(tid), membership_role="admin"))
            db.add(
                AuditLog(
                    actor_user_id=user_ctx["user"].id,
                    actor_role=user_ctx["role"],
                    tenant_id=uuid.UUID(tid),
                    action="user_tenant_added",
                    target_type="user_tenant",
                    target_id=f"{user_id}:{tid}",
                    details_json={"user_id": user_id, "tenant_id": tid},
                )
            )

    db.commit()
    return {"status": "ok", "user_id": user_id, "tenant_ids": next_ids}


@app.get("/api/admin/visitors")
async def admin_visitors(
    user_ctx=Depends(get_current_user),
    db=Depends(db_session),
    tenant_id: Optional[str] = Query(default=None),
    page: int = Query(default=1),
    page_size: int = Query(default=20),
):
    page = max(page, 1)
    page_size = max(1, min(page_size, 100))
    effective_tenant_id = resolve_effective_tenant_id_for_admin_views(db, user_ctx, tenant_id)
    sessions = db.execute(
        select(ChatSession)
        .where(ChatSession.tenant_id == uuid.UUID(effective_tenant_id), ChatSession.visitor_id.is_not(None))
        .order_by(ChatSession.last_message_at.desc())
    ).scalars().all()
    visitors_by_id: dict[str, dict[str, Any]] = {}
    for s in sessions:
        vid = s.visitor_id
        if not vid:
            continue
        row = visitors_by_id.get(vid)
        started_at = s.started_at or s.created_at
        if not row:
            visitors_by_id[vid] = {
                "visitor_id": vid,
                "name": s.visitor_name,
                "email": s.visitor_email,
                "first_seen_at": started_at.isoformat() if started_at else None,
                "last_seen_at": s.last_message_at.isoformat() if s.last_message_at else None,
                "chat_count": 1,
            }
            continue
        row["chat_count"] += 1
        if not row.get("name") and s.visitor_name:
            row["name"] = s.visitor_name
        if not row.get("email") and s.visitor_email:
            row["email"] = s.visitor_email
        if started_at and row.get("first_seen_at"):
            row["first_seen_at"] = min(datetime.fromisoformat(row["first_seen_at"]), started_at).isoformat()
        elif started_at and not row.get("first_seen_at"):
            row["first_seen_at"] = started_at.isoformat()
        if s.last_message_at and row.get("last_seen_at"):
            row["last_seen_at"] = max(datetime.fromisoformat(row["last_seen_at"]), s.last_message_at).isoformat()
        elif s.last_message_at and not row.get("last_seen_at"):
            row["last_seen_at"] = s.last_message_at.isoformat()
    visitors = list(visitors_by_id.values())
    visitors.sort(key=lambda item: item.get("last_seen_at") or "", reverse=True)
    total = len(visitors)
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    items = visitors[start_idx:end_idx]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@app.get("/api/admin/visitors/{visitor_id}/chats")
async def admin_visitor_chats(
    visitor_id: str,
    user_ctx=Depends(get_current_user),
    db=Depends(db_session),
    tenant_id: Optional[str] = Query(default=None),
    page: int = Query(default=1),
    page_size: int = Query(default=20),
):
    page = max(page, 1)
    page_size = max(1, min(page_size, 100))
    effective_tenant_id = resolve_effective_tenant_id_for_admin_views(db, user_ctx, tenant_id)
    sessions = db.execute(
        select(ChatSession)
        .where(
            ChatSession.tenant_id == uuid.UUID(effective_tenant_id),
            ChatSession.visitor_id == visitor_id,
        )
        .order_by(ChatSession.last_message_at.desc())
    ).scalars().all()
    session_ids = [s.id for s in sessions]
    feedback_by_session = {}
    if session_ids:
        message_rows = db.execute(select(ChatMessage.id, ChatMessage.session_id).where(ChatMessage.session_id.in_(session_ids))).all()
        message_to_session = {m_id: s_id for m_id, s_id in message_rows}
        message_ids = list(message_to_session.keys())
        if message_ids:
            feedback_rows = db.execute(
                select(MessageFeedback.message_id, MessageFeedback.vote).where(MessageFeedback.message_id.in_(message_ids))
            ).all()
            for message_id, vote in feedback_rows:
                sid = str(message_to_session.get(message_id))
                if sid not in feedback_by_session:
                    feedback_by_session[sid] = {"up": 0, "down": 0}
                if vote == FeedbackVote.up:
                    feedback_by_session[sid]["up"] += 1
                elif vote == FeedbackVote.down:
                    feedback_by_session[sid]["down"] += 1
    total = len(sessions)
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    sessions_page = sessions[start_idx:end_idx]
    items = [
        {
            "id": str(s.id),
            "title": s.title,
            "last_message_at": s.last_message_at.isoformat() if s.last_message_at else None,
            "feedback_summary": feedback_by_session.get(str(s.id), {"up": 0, "down": 0}),
        }
        for s in sessions_page
    ]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@app.get("/api/admin/reference/countries")
async def admin_reference_countries(_user_ctx=Depends(get_current_user)):
    """ISO 3166-1 alpha-2 list for Security country block UI; matches Country MMDB `iso_code` (e.g. DB-IP Lite)."""
    import pycountry

    items = []
    for c in pycountry.countries:
        code = getattr(c, "alpha_2", None)
        if code:
            items.append({"code": code, "name": c.name})
    items.sort(key=lambda x: (x["name"].lower(), x["code"]))
    return {
        "countries": items,
        "standard": "ISO 3166-1 alpha-2",
        "geoip_note": "Same codes as GeoIP Country databases (e.g. dbip-country-lite.mmdb country iso_code).",
    }


@app.get("/api/admin/tenants")
async def admin_tenants(user_ctx=Depends(get_current_user), db=Depends(db_session)):
    if user_ctx["role"] == UserRole.superadmin.value:
        tenants = db.execute(select(Tenant).order_by(Tenant.created_at.desc())).scalars().all()
    else:
        tenant_ids = get_accessible_tenant_ids(db, user_ctx)
        tenant_rows = db.execute(select(Tenant).where(Tenant.id.in_([uuid.UUID(tid) for tid in tenant_ids]))).scalars().all() if tenant_ids else []
        tenants = sorted(tenant_rows, key=lambda t: t.created_at, reverse=True)
    return [
        {
            "id": str(t.id),
            "name": t.name,
            "slug": t.slug,
            "status": t.status,
            "source_db_url": t.source_db_url,
            "source_db_type": t.source_db_type,
            "source_table_prefix": t.source_table_prefix,
            "source_url_table": t.source_url_table,
            "source_mode": t.source_mode,
            "source_static_urls_json": t.source_static_urls_json,
            "source_domain_aliases": t.source_domain_aliases,
            "source_canonical_base_url": t.source_canonical_base_url,
            "has_source_db_url": bool(t.source_db_url),
            "brand_name": t.brand_name,
            "widget_primary_color": t.widget_primary_color,
            "widget_website_url": t.widget_website_url,
            "widget_source_type": t.widget_source_type,
            "widget_user_message_color": t.widget_user_message_color,
            "widget_bot_message_color": t.widget_bot_message_color,
            "widget_user_message_text_color": t.widget_user_message_text_color,
            "widget_bot_message_text_color": t.widget_bot_message_text_color,
            "widget_header_title": t.widget_header_title,
            "widget_welcome_message": t.widget_welcome_message,
            "privacy_policy_url": t.privacy_policy_url,
            "avatar_url": _normalize_avatar_url_for_widget(t.avatar_url),
            "cors_allowed_origins": t.cors_allowed_origins,
            "idle_rating_wait_seconds": t.idle_rating_wait_seconds,
        }
        for t in tenants
    ]


@app.post("/api/admin/tenants")
async def create_admin_tenant(payload: TenantCreateRequest, user_ctx=Depends(get_current_user), db=Depends(db_session)):
    require_role(user_ctx, [UserRole.superadmin.value, UserRole.admin.value])
    tenant_name = (payload.name or "").strip()
    if not tenant_name:
        raise HTTPException(status_code=400, detail="name is required")
    existing_tenant = db.execute(select(Tenant).where(Tenant.name == tenant_name)).scalar_one_or_none()
    if existing_tenant:
        raise HTTPException(status_code=400, detail="Tenant name already in use")
    base_slug = _slugify(tenant_name)
    slug = base_slug
    suffix = 1
    while db.execute(select(Tenant).where(Tenant.slug == slug)).scalar_one_or_none():
        suffix += 1
        slug = f"{base_slug}-{suffix}"
    tenant = Tenant(name=tenant_name, slug=slug, status="active")
    db.add(tenant)
    db.flush()
    seed_quick_replies_for_tenant(db, tenant.id)
    if user_ctx["role"] == UserRole.admin.value:
        db.add(UserTenant(user_id=user_ctx["user"].id, tenant_id=tenant.id, membership_role="owner"))
    db.add(
        AuditLog(
            actor_user_id=user_ctx["user"].id,
            actor_role=user_ctx["role"],
            tenant_id=tenant.id,
            action="tenant_created",
            target_type="tenant",
            target_id=str(tenant.id),
            details_json={"name": tenant.name, "slug": tenant.slug},
        )
    )
    db.commit()
    return {"id": str(tenant.id), "name": tenant.name, "slug": tenant.slug, "status": tenant.status}


@app.patch("/api/admin/tenants/{tenant_id}/source-config")
async def update_tenant_source_config(tenant_id: str, payload: TenantSourceConfigRequest, user_ctx=Depends(get_current_user), db=Depends(db_session)):
    tenant = db.get(Tenant, uuid.UUID(tenant_id))
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if user_ctx["role"] != UserRole.superadmin.value and str(tenant.id) not in get_accessible_tenant_ids(db, user_ctx):
        raise HTTPException(status_code=403, detail="Forbidden")

    source_mode = (payload.source_mode or "").strip().lower() if payload.source_mode is not None else None
    if source_mode is not None and source_mode not in {"wordpress", "static", "mixed", ""}:
        raise HTTPException(status_code=400, detail="source_mode must be one of: wordpress, static, mixed")
    source_mode = source_mode or None

    canonical_base = None
    if payload.source_canonical_base_url is not None:
        canonical_base = (payload.source_canonical_base_url or "").strip() or None
        if canonical_base and not _is_http_url(canonical_base):
            raise HTTPException(status_code=400, detail="source_canonical_base_url must be a valid http(s) URL")

    domain_aliases_csv = None
    alias_values: List[str] = []
    if payload.source_domain_aliases is not None:
        raw_aliases = payload.source_domain_aliases.strip()
        if raw_aliases:
            alias_values = [a.strip() for a in re.split(r"[,\n]+", raw_aliases) if a.strip()]
            invalid_aliases = [a for a in alias_values if not _is_http_url(a)]
            if invalid_aliases:
                raise HTTPException(status_code=400, detail="source_domain_aliases must be comma/newline separated http(s) URLs")
            domain_aliases_csv = ",".join(alias_values)

    source_static_urls_json = _normalize_source_static_urls_json(
        payload.source_static_urls_json,
        domain_aliases=alias_values,
        canonical_base=canonical_base,
    )

    tenant.source_db_url = payload.source_db_url
    tenant.source_db_type = payload.source_db_type
    tenant.source_table_prefix = payload.source_table_prefix
    tenant.source_url_table = payload.source_url_table
    tenant.source_mode = source_mode
    tenant.source_static_urls_json = source_static_urls_json
    tenant.source_domain_aliases = domain_aliases_csv
    tenant.source_canonical_base_url = canonical_base
    tenant.updated_at = datetime.now(timezone.utc)
    db.add(
        AuditLog(
            actor_user_id=user_ctx["user"].id,
            actor_role=user_ctx["role"],
            tenant_id=tenant.id,
            action="tenant_source_config_updated",
            target_type="tenant",
            target_id=str(tenant.id),
            details_json={
                "source_db_type": payload.source_db_type,
                "source_mode": source_mode,
                "static_url_count": len(json.loads(source_static_urls_json or "[]")),
            },
        )
    )
    db.commit()
    return {"status": "ok", "tenant_id": str(tenant.id)}


@app.patch("/api/admin/tenants/{tenant_id}/branding")
async def update_tenant_branding(
    tenant_id: str,
    payload: TenantBrandingConfigRequest,
    user_ctx=Depends(get_current_user),
    db=Depends(db_session),
):
    _ensure_manage_tenant(db, user_ctx, tenant_id)
    tenant = db.get(Tenant, uuid.UUID(tenant_id))
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if payload.brand_name is not None:
        tenant.brand_name = payload.brand_name.strip() or None
    if payload.widget_primary_color is not None:
        color_value = payload.widget_primary_color.strip() if payload.widget_primary_color else ""
        if color_value and not re.fullmatch(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$", color_value):
            raise HTTPException(status_code=400, detail="widget_primary_color must be a valid hex color")
        tenant.widget_primary_color = color_value or None
    if payload.widget_website_url is not None:
        wu = payload.widget_website_url.strip() if payload.widget_website_url else ""
        if wu and not (wu.startswith("http://") or wu.startswith("https://")):
            raise HTTPException(status_code=400, detail="widget_website_url must be a valid URL")
        tenant.widget_website_url = wu or None
    if payload.widget_source_type is not None:
        st = payload.widget_source_type.strip() if payload.widget_source_type else ""
        if st and not re.fullmatch(r"^[a-zA-Z0-9_.-]{1,64}$", st):
            raise HTTPException(
                status_code=400,
                detail="widget_source_type must be 1-64 characters: letters, digits, underscore, hyphen, or dot",
            )
        tenant.widget_source_type = st or None
    if payload.widget_user_message_color is not None:
        uc = payload.widget_user_message_color.strip() if payload.widget_user_message_color else ""
        if uc and not re.fullmatch(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$", uc):
            raise HTTPException(status_code=400, detail="widget_user_message_color must be a valid hex color")
        tenant.widget_user_message_color = uc or None
    if payload.widget_bot_message_color is not None:
        bc = payload.widget_bot_message_color.strip() if payload.widget_bot_message_color else ""
        if bc and not re.fullmatch(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$", bc):
            raise HTTPException(status_code=400, detail="widget_bot_message_color must be a valid hex color")
        tenant.widget_bot_message_color = bc or None
    if payload.widget_user_message_text_color is not None:
        utc = payload.widget_user_message_text_color.strip() if payload.widget_user_message_text_color else ""
        if utc and not re.fullmatch(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$", utc):
            raise HTTPException(status_code=400, detail="widget_user_message_text_color must be a valid hex color")
        tenant.widget_user_message_text_color = utc or None
    if payload.widget_bot_message_text_color is not None:
        btc = payload.widget_bot_message_text_color.strip() if payload.widget_bot_message_text_color else ""
        if btc and not re.fullmatch(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$", btc):
            raise HTTPException(status_code=400, detail="widget_bot_message_text_color must be a valid hex color")
        tenant.widget_bot_message_text_color = btc or None
    if payload.widget_header_title is not None:
        tenant.widget_header_title = payload.widget_header_title.strip() or None
    if payload.widget_welcome_message is not None:
        tenant.widget_welcome_message = payload.widget_welcome_message.strip() or None
    if payload.privacy_policy_url is not None:
        privacy_url = payload.privacy_policy_url.strip() if payload.privacy_policy_url else ""
        if privacy_url and not (privacy_url.startswith("http://") or privacy_url.startswith("https://")):
            raise HTTPException(status_code=400, detail="privacy_policy_url must be a valid URL")
        tenant.privacy_policy_url = privacy_url or None
    if payload.avatar_url is not None:
        new_val = payload.avatar_url.strip() or None
        if new_val is None:
            remove_local_avatar_files_for_tenant(tenant_id)
        tenant.avatar_url = new_val
    if payload.cors_allowed_origins is not None:
        tenant.cors_allowed_origins = payload.cors_allowed_origins.strip() or None

    db.add(
        AuditLog(
            actor_user_id=user_ctx["user"].id,
            actor_role=user_ctx["role"],
            tenant_id=tenant.id,
            action="tenant_branding_updated",
            target_type="tenant",
            target_id=str(tenant.id),
            details_json={"brand_name": tenant.brand_name, "has_avatar": bool(tenant.avatar_url)},
        )
    )
    db.commit()
    return {"status": "ok", "tenant_id": tenant_id}


@app.post("/api/admin/tenants/{tenant_id}/avatar")
async def upload_tenant_avatar(
    tenant_id: str,
    file: UploadFile = File(...),
    user_ctx=Depends(get_current_user),
    db=Depends(db_session),
):
    _ensure_manage_tenant(db, user_ctx, tenant_id)
    tenant = db.get(Tenant, uuid.UUID(tenant_id))
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if not (file.content_type or "").startswith("image/"):
        raise HTTPException(status_code=400, detail="Only image files are allowed")
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Avatar exceeds 10MB limit")
    uploads_dir = ensure_tenant_assets_dir()
    remove_local_avatar_files_for_tenant(tenant_id)
    ext = os.path.splitext(file.filename or "")[1].lower() or ".png"
    output_name = next_avatar_filename(tenant_id, ext)
    output_path = os.path.join(uploads_dir, output_name)
    with open(output_path, "wb") as f:
        f.write(content)
    tenant.avatar_url = f"/api/assets/{output_name}"
    db.add(
        AuditLog(
            actor_user_id=user_ctx["user"].id,
            actor_role=user_ctx["role"],
            tenant_id=tenant.id,
            action="tenant_avatar_uploaded",
            target_type="tenant",
            target_id=str(tenant.id),
            details_json={"filename": output_name},
        )
    )
    db.commit()
    return {"status": "ok", "avatar_url": tenant.avatar_url}


@app.get("/api/assets/{filename}")
async def get_uploaded_asset(filename: str):
    from fastapi.responses import FileResponse

    uploads_dir = tenant_assets_dir()
    safe_name = os.path.basename(filename)
    path = os.path.join(uploads_dir, safe_name)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Asset not found")
    return FileResponse(path)


@app.get("/api/admin/tenants/{tenant_id}/security")
async def get_tenant_security_settings(tenant_id: str, user_ctx=Depends(get_current_user), db=Depends(db_session)):
    _ensure_manage_tenant(db, user_ctx, tenant_id)
    tenant = db.get(Tenant, uuid.UUID(tenant_id))
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    blocked_ips = db.execute(
        select(TenantBlockedIP).where(TenantBlockedIP.tenant_id == tenant.id).order_by(TenantBlockedIP.created_at.desc())
    ).scalars().all()
    blocked_countries = db.execute(
        select(TenantBlockedCountry).where(TenantBlockedCountry.tenant_id == tenant.id).order_by(TenantBlockedCountry.created_at.desc())
    ).scalars().all()
    return {
        "tenant_id": tenant_id,
        "monthly_message_limit": tenant.monthly_message_limit,
        "quota_reached_message": tenant.quota_reached_message,
        "idle_rating_wait_seconds": tenant.idle_rating_wait_seconds,
        "cors_allowed_origins": tenant.cors_allowed_origins or "",
        "blocked_ips": [{"id": str(item.id), "ip_address": item.ip_address, "reason": item.reason} for item in blocked_ips],
        "blocked_countries": [{"id": str(item.id), "country_code": item.country_code, "reason": item.reason} for item in blocked_countries],
    }


@app.patch("/api/admin/tenants/{tenant_id}/idle-rating")
async def update_tenant_idle_rating_settings(
    tenant_id: str,
    payload: TenantIdleRatingConfigRequest,
    user_ctx=Depends(get_current_user),
    db=Depends(db_session),
):
    _ensure_manage_tenant(db, user_ctx, tenant_id)
    tenant = db.get(Tenant, uuid.UUID(tenant_id))
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if payload.idle_rating_wait_seconds < 5:
        raise HTTPException(status_code=400, detail="idle_rating_wait_seconds must be >= 5")
    tenant.idle_rating_wait_seconds = int(payload.idle_rating_wait_seconds)
    db.add(
        AuditLog(
            actor_user_id=user_ctx["user"].id,
            actor_role=user_ctx["role"],
            tenant_id=tenant.id,
            action="tenant_idle_rating_updated",
            target_type="tenant",
            target_id=str(tenant.id),
            details_json={"idle_rating_wait_seconds": tenant.idle_rating_wait_seconds},
        )
    )
    db.commit()
    return {"status": "ok", "tenant_id": tenant_id, "idle_rating_wait_seconds": tenant.idle_rating_wait_seconds}


@app.get("/api/admin/tenants/{tenant_id}/block-word-categories")
async def list_tenant_block_word_categories(
    tenant_id: str,
    user_ctx=Depends(get_current_user),
    db=Depends(db_session),
):
    _ensure_manage_tenant(db, user_ctx, tenant_id)
    tenant = db.get(Tenant, uuid.UUID(tenant_id))
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    categories = db.execute(
        select(TenantBlockWordCategory)
        .where(TenantBlockWordCategory.tenant_id == tenant.id)
        .order_by(TenantBlockWordCategory.created_at.desc())
    ).scalars().all()
    response = []
    for category in categories:
        words = db.execute(
            select(TenantBlockWord).where(TenantBlockWord.category_id == category.id).order_by(TenantBlockWord.created_at.asc())
        ).scalars().all()
        response.append(
            {
                "id": str(category.id),
                "name": category.name,
                "match_mode": str(category.match_mode),
                "response_message": category.response_message,
                "words": [{"id": str(w.id), "word": w.word} for w in words],
            }
        )
    return response


@app.post("/api/admin/tenants/{tenant_id}/block-word-categories")
async def create_tenant_block_word_category(
    tenant_id: str,
    payload: BlockWordCategoryRequest,
    user_ctx=Depends(get_current_user),
    db=Depends(db_session),
):
    _ensure_manage_tenant(db, user_ctx, tenant_id)
    tenant = db.get(Tenant, uuid.UUID(tenant_id))
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    name = payload.name.strip()
    response_message = payload.response_message.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Category name is required")
    if not response_message:
        raise HTTPException(status_code=400, detail="response_message is required")
    mode_raw = (payload.match_mode or "").strip().lower()
    allowed_modes = {m.value for m in BlockWordMatchMode}
    if mode_raw not in allowed_modes:
        raise HTTPException(status_code=400, detail="match_mode must be exact, substring, or regex")
    existing = db.execute(
        select(TenantBlockWordCategory).where(
            TenantBlockWordCategory.tenant_id == tenant.id,
            TenantBlockWordCategory.name == name,
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail="Category already exists")
    category = TenantBlockWordCategory(
        tenant_id=tenant.id,
        name=name,
        match_mode=mode_raw,
        response_message=response_message,
    )
    db.add(category)
    db.add(
        AuditLog(
            actor_user_id=user_ctx["user"].id,
            actor_role=user_ctx["role"],
            tenant_id=tenant.id,
            action="tenant_block_word_category_added",
            target_type="tenant_block_word_category",
            target_id=name,
            details_json={"match_mode": mode_raw},
        )
    )
    db.commit()
    return {"status": "ok", "id": str(category.id), "name": category.name}


@app.patch("/api/admin/tenants/{tenant_id}/block-word-categories/{category_id}")
async def update_tenant_block_word_category(
    tenant_id: str,
    category_id: str,
    payload: BlockWordCategoryRequest,
    user_ctx=Depends(get_current_user),
    db=Depends(db_session),
):
    _ensure_manage_tenant(db, user_ctx, tenant_id)
    category = db.get(TenantBlockWordCategory, uuid.UUID(category_id))
    if not category or str(category.tenant_id) != tenant_id:
        raise HTTPException(status_code=404, detail="Category not found")
    name = payload.name.strip()
    response_message = payload.response_message.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Category name is required")
    if not response_message:
        raise HTTPException(status_code=400, detail="response_message is required")
    mode_raw = (payload.match_mode or "").strip().lower()
    allowed_modes = {m.value for m in BlockWordMatchMode}
    if mode_raw not in allowed_modes:
        raise HTTPException(status_code=400, detail="match_mode must be exact, substring, or regex")
    category.name = name
    category.match_mode = mode_raw
    category.response_message = response_message
    db.add(
        AuditLog(
            actor_user_id=user_ctx["user"].id,
            actor_role=user_ctx["role"],
            tenant_id=category.tenant_id,
            action="tenant_block_word_category_updated",
            target_type="tenant_block_word_category",
            target_id=str(category.id),
            details_json={"name": category.name, "match_mode": mode_raw},
        )
    )
    db.commit()
    return {"status": "ok", "id": str(category.id)}


@app.delete("/api/admin/tenants/{tenant_id}/block-word-categories/{category_id}")
async def delete_tenant_block_word_category(
    tenant_id: str,
    category_id: str,
    user_ctx=Depends(get_current_user),
    db=Depends(db_session),
):
    _ensure_manage_tenant(db, user_ctx, tenant_id)
    category = db.get(TenantBlockWordCategory, uuid.UUID(category_id))
    if not category or str(category.tenant_id) != tenant_id:
        raise HTTPException(status_code=404, detail="Category not found")
    words = db.execute(select(TenantBlockWord).where(TenantBlockWord.category_id == category.id)).scalars().all()
    for word in words:
        db.delete(word)
    db.delete(category)
    db.add(
        AuditLog(
            actor_user_id=user_ctx["user"].id,
            actor_role=user_ctx["role"],
            tenant_id=uuid.UUID(tenant_id),
            action="tenant_block_word_category_removed",
            target_type="tenant_block_word_category",
            target_id=category_id,
            details_json={},
        )
    )
    db.commit()
    return {"status": "ok", "id": category_id}


@app.post("/api/admin/tenants/{tenant_id}/block-word-categories/{category_id}/words")
async def add_tenant_block_word(
    tenant_id: str,
    category_id: str,
    payload: BlockWordRequest,
    user_ctx=Depends(get_current_user),
    db=Depends(db_session),
):
    _ensure_manage_tenant(db, user_ctx, tenant_id)
    category = db.get(TenantBlockWordCategory, uuid.UUID(category_id))
    if not category or str(category.tenant_id) != tenant_id:
        raise HTTPException(status_code=404, detail="Category not found")
    word_value = (payload.word or "").strip()
    if not word_value:
        raise HTTPException(status_code=400, detail="word is required")
    existing = db.execute(
        select(TenantBlockWord).where(
            TenantBlockWord.category_id == category.id,
            TenantBlockWord.word == word_value,
        )
    ).scalar_one_or_none()
    if existing:
        return {"status": "ok", "id": str(existing.id), "word": existing.word}
    block_word = TenantBlockWord(category_id=category.id, word=word_value)
    db.add(block_word)
    db.add(
        AuditLog(
            actor_user_id=user_ctx["user"].id,
            actor_role=user_ctx["role"],
            tenant_id=uuid.UUID(tenant_id),
            action="tenant_block_word_added",
            target_type="tenant_block_word",
            target_id=word_value,
            details_json={"category_id": category_id},
        )
    )
    db.commit()
    return {"status": "ok", "id": str(block_word.id), "word": block_word.word}


@app.delete("/api/admin/tenants/{tenant_id}/block-word-categories/{category_id}/words/{word_id}")
async def delete_tenant_block_word(
    tenant_id: str,
    category_id: str,
    word_id: str,
    user_ctx=Depends(get_current_user),
    db=Depends(db_session),
):
    _ensure_manage_tenant(db, user_ctx, tenant_id)
    category = db.get(TenantBlockWordCategory, uuid.UUID(category_id))
    if not category or str(category.tenant_id) != tenant_id:
        raise HTTPException(status_code=404, detail="Category not found")
    block_word = db.get(TenantBlockWord, uuid.UUID(word_id))
    if not block_word or str(block_word.category_id) != category_id:
        raise HTTPException(status_code=404, detail="Word not found")
    db.delete(block_word)
    db.add(
        AuditLog(
            actor_user_id=user_ctx["user"].id,
            actor_role=user_ctx["role"],
            tenant_id=uuid.UUID(tenant_id),
            action="tenant_block_word_removed",
            target_type="tenant_block_word",
            target_id=word_id,
            details_json={"category_id": category_id},
        )
    )
    db.commit()
    return {"status": "ok", "id": word_id}


def _quick_reply_api_dict(row: TenantQuickReply, tenant: Optional[Tenant]) -> dict:
    from fuzzy_matcher import substitute_quick_reply_template

    return {
        "id": str(row.id),
        "category": row.category,
        "trigger_phrase": row.trigger_phrase,
        "response_template": row.response_template,
        "similarity_threshold": row.similarity_threshold,
        "priority": row.priority,
        "enabled": row.enabled,
        "rendered_preview": substitute_quick_reply_template(tenant, row.response_template) if tenant else row.response_template,
    }


async def list_tenant_quick_replies_for_admin(tenant_id: str, user_ctx: dict, db):
    _ensure_manage_tenant(db, user_ctx, tenant_id)
    tenant = db.get(Tenant, uuid.UUID(tenant_id))
    rows = db.execute(
        select(TenantQuickReply)
        .where(TenantQuickReply.tenant_id == uuid.UUID(tenant_id))
        .order_by(TenantQuickReply.category.asc(), TenantQuickReply.priority.desc(), TenantQuickReply.trigger_phrase.asc())
    ).scalars().all()
    return [_quick_reply_api_dict(r, tenant) for r in rows]


async def create_tenant_quick_reply_for_admin(
    tenant_id: str,
    payload: QuickReplyCreateRequest,
    user_ctx: dict,
    db,
):
    _ensure_manage_tenant(db, user_ctx, tenant_id)
    tenant = db.get(Tenant, uuid.UUID(tenant_id))
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    trig = normalize_trigger_phrase(payload.trigger_phrase)
    if not trig:
        raise HTTPException(status_code=400, detail="trigger_phrase is required")
    if payload.similarity_threshold is not None and not (50 <= payload.similarity_threshold <= 100):
        raise HTTPException(status_code=400, detail="similarity_threshold must be between 50 and 100")
    exists = db.execute(
        select(TenantQuickReply).where(
            TenantQuickReply.tenant_id == tenant.id,
            TenantQuickReply.trigger_phrase == trig,
        )
    ).scalars().first()
    if exists:
        raise HTTPException(status_code=400, detail="A quick reply with this trigger already exists")
    row = TenantQuickReply(
        tenant_id=tenant.id,
        category=(payload.category or "general").strip()[:64] or "general",
        trigger_phrase=trig,
        response_template=payload.response_template,
        similarity_threshold=payload.similarity_threshold,
        priority=payload.priority,
        enabled=payload.enabled,
    )
    db.add(row)
    db.add(
        AuditLog(
            actor_user_id=user_ctx["user"].id,
            actor_role=user_ctx["role"],
            tenant_id=tenant.id,
            action="tenant_quick_reply_created",
            target_type="tenant_quick_reply",
            target_id=str(row.id),
            details_json={"trigger_phrase": trig},
        )
    )
    db.commit()
    db.refresh(row)
    return _quick_reply_api_dict(row, tenant)


async def update_tenant_quick_reply_for_admin(
    tenant_id: str,
    quick_reply_id: str,
    payload: QuickReplyUpdateRequest,
    user_ctx: dict,
    db,
):
    _ensure_manage_tenant(db, user_ctx, tenant_id)
    tenant = db.get(Tenant, uuid.UUID(tenant_id))
    row = db.get(TenantQuickReply, uuid.UUID(quick_reply_id))
    if not row or str(row.tenant_id) != tenant_id:
        raise HTTPException(status_code=404, detail="Quick reply not found")
    if payload.category is not None:
        row.category = (payload.category or "general").strip()[:64] or "general"
    if payload.trigger_phrase is not None:
        trig = normalize_trigger_phrase(payload.trigger_phrase)
        if not trig:
            raise HTTPException(status_code=400, detail="trigger_phrase is required")
        conflict = db.execute(
            select(TenantQuickReply).where(
                TenantQuickReply.tenant_id == row.tenant_id,
                TenantQuickReply.trigger_phrase == trig,
                TenantQuickReply.id != row.id,
            )
        ).scalars().first()
        if conflict:
            raise HTTPException(status_code=400, detail="Another quick reply already uses this trigger")
        row.trigger_phrase = trig
    if payload.response_template is not None:
        row.response_template = payload.response_template
    if payload.similarity_threshold is not None:
        if payload.similarity_threshold < 50 or payload.similarity_threshold > 100:
            raise HTTPException(status_code=400, detail="similarity_threshold must be between 50 and 100")
        row.similarity_threshold = payload.similarity_threshold
    if payload.priority is not None:
        row.priority = payload.priority
    if payload.enabled is not None:
        row.enabled = payload.enabled
    db.add(
        AuditLog(
            actor_user_id=user_ctx["user"].id,
            actor_role=user_ctx["role"],
            tenant_id=row.tenant_id,
            action="tenant_quick_reply_updated",
            target_type="tenant_quick_reply",
            target_id=str(row.id),
            details_json={},
        )
    )
    db.commit()
    db.refresh(row)
    return _quick_reply_api_dict(row, tenant)


async def delete_tenant_quick_reply_for_admin(
    tenant_id: str,
    quick_reply_id: str,
    user_ctx: dict,
    db,
):
    _ensure_manage_tenant(db, user_ctx, tenant_id)
    row = db.get(TenantQuickReply, uuid.UUID(quick_reply_id))
    if not row or str(row.tenant_id) != tenant_id:
        raise HTTPException(status_code=404, detail="Quick reply not found")
    db.delete(row)
    db.add(
        AuditLog(
            actor_user_id=user_ctx["user"].id,
            actor_role=user_ctx["role"],
            tenant_id=uuid.UUID(tenant_id),
            action="tenant_quick_reply_deleted",
            target_type="tenant_quick_reply",
            target_id=quick_reply_id,
            details_json={},
        )
    )
    db.commit()
    return {"status": "ok", "id": quick_reply_id}


@app.patch("/api/admin/tenants/{tenant_id}/quota")
async def update_tenant_quota_settings(
    tenant_id: str,
    payload: TenantQuotaConfigRequest,
    user_ctx=Depends(get_current_user),
    db=Depends(db_session),
):
    _ensure_manage_tenant(db, user_ctx, tenant_id)
    tenant = db.get(Tenant, uuid.UUID(tenant_id))
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    if payload.monthly_message_limit is not None:
        require_role(user_ctx, [UserRole.superadmin.value])
        if payload.monthly_message_limit < 1:
            raise HTTPException(status_code=400, detail="monthly_message_limit must be positive")
        tenant.monthly_message_limit = payload.monthly_message_limit
    if payload.quota_reached_message is not None:
        tenant.quota_reached_message = payload.quota_reached_message.strip() or tenant.quota_reached_message

    db.add(
        AuditLog(
            actor_user_id=user_ctx["user"].id,
            actor_role=user_ctx["role"],
            tenant_id=tenant.id,
            action="tenant_quota_updated",
            target_type="tenant",
            target_id=str(tenant.id),
            details_json={
                "monthly_message_limit": tenant.monthly_message_limit,
                "quota_reached_message_updated": payload.quota_reached_message is not None,
            },
        )
    )
    db.commit()
    return {
        "status": "ok",
        "tenant_id": tenant_id,
        "monthly_message_limit": tenant.monthly_message_limit,
        "quota_reached_message": tenant.quota_reached_message,
    }


@app.post("/api/admin/tenants/{tenant_id}/blocked-ips")
async def add_tenant_blocked_ip(
    tenant_id: str,
    payload: BlockedIPRequest,
    user_ctx=Depends(get_current_user),
    db=Depends(db_session),
):
    _ensure_manage_tenant(db, user_ctx, tenant_id)
    tenant = db.get(Tenant, uuid.UUID(tenant_id))
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    ip_value = payload.ip_address.strip()
    try:
        ip_value = str(ipaddress.ip_address(ip_value))
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid IP address") from exc
    existing = db.execute(
        select(TenantBlockedIP).where(TenantBlockedIP.tenant_id == tenant.id, TenantBlockedIP.ip_address == ip_value)
    ).scalar_one_or_none()
    if existing:
        return {"status": "ok", "id": str(existing.id), "ip_address": existing.ip_address, "reason": existing.reason}
    blocked = TenantBlockedIP(tenant_id=tenant.id, ip_address=ip_value, reason=(payload.reason or "").strip())
    db.add(blocked)
    db.add(
        AuditLog(
            actor_user_id=user_ctx["user"].id,
            actor_role=user_ctx["role"],
            tenant_id=tenant.id,
            action="tenant_blocked_ip_added",
            target_type="tenant_blocked_ip",
            target_id=ip_value,
            details_json={"reason": blocked.reason},
        )
    )
    db.commit()
    return {"status": "ok", "id": str(blocked.id), "ip_address": blocked.ip_address, "reason": blocked.reason}


@app.delete("/api/admin/tenants/{tenant_id}/blocked-ips/{blocked_ip_id}")
async def remove_tenant_blocked_ip(
    tenant_id: str,
    blocked_ip_id: str,
    user_ctx=Depends(get_current_user),
    db=Depends(db_session),
):
    _ensure_manage_tenant(db, user_ctx, tenant_id)
    blocked = db.get(TenantBlockedIP, uuid.UUID(blocked_ip_id))
    if not blocked or str(blocked.tenant_id) != tenant_id:
        raise HTTPException(status_code=404, detail="Blocked IP not found")
    db.delete(blocked)
    db.add(
        AuditLog(
            actor_user_id=user_ctx["user"].id,
            actor_role=user_ctx["role"],
            tenant_id=blocked.tenant_id,
            action="tenant_blocked_ip_removed",
            target_type="tenant_blocked_ip",
            target_id=blocked.ip_address,
            details_json={},
        )
    )
    db.commit()
    return {"status": "ok"}


@app.post("/api/admin/tenants/{tenant_id}/blocked-countries")
async def add_tenant_blocked_country(
    tenant_id: str,
    payload: BlockedCountryRequest,
    user_ctx=Depends(get_current_user),
    db=Depends(db_session),
):
    _ensure_manage_tenant(db, user_ctx, tenant_id)
    tenant = db.get(Tenant, uuid.UUID(tenant_id))
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    country_code = (payload.country_code or "").strip().upper()
    if len(country_code) != 2 or not country_code.isalpha():
        raise HTTPException(status_code=400, detail="country_code must be ISO alpha-2")
    existing = db.execute(
        select(TenantBlockedCountry).where(
            TenantBlockedCountry.tenant_id == tenant.id,
            TenantBlockedCountry.country_code == country_code,
        )
    ).scalar_one_or_none()
    if existing:
        return {"status": "ok", "id": str(existing.id), "country_code": existing.country_code, "reason": existing.reason}
    blocked = TenantBlockedCountry(tenant_id=tenant.id, country_code=country_code, reason=(payload.reason or "").strip())
    db.add(blocked)
    db.add(
        AuditLog(
            actor_user_id=user_ctx["user"].id,
            actor_role=user_ctx["role"],
            tenant_id=tenant.id,
            action="tenant_blocked_country_added",
            target_type="tenant_blocked_country",
            target_id=country_code,
            details_json={"reason": blocked.reason},
        )
    )
    db.commit()
    return {"status": "ok", "id": str(blocked.id), "country_code": blocked.country_code, "reason": blocked.reason}


@app.delete("/api/admin/tenants/{tenant_id}/blocked-countries/{blocked_country_id}")
async def remove_tenant_blocked_country(
    tenant_id: str,
    blocked_country_id: str,
    user_ctx=Depends(get_current_user),
    db=Depends(db_session),
):
    _ensure_manage_tenant(db, user_ctx, tenant_id)
    blocked = db.get(TenantBlockedCountry, uuid.UUID(blocked_country_id))
    if not blocked or str(blocked.tenant_id) != tenant_id:
        raise HTTPException(status_code=404, detail="Blocked country not found")
    db.delete(blocked)
    db.add(
        AuditLog(
            actor_user_id=user_ctx["user"].id,
            actor_role=user_ctx["role"],
            tenant_id=blocked.tenant_id,
            action="tenant_blocked_country_removed",
            target_type="tenant_blocked_country",
            target_id=blocked.country_code,
            details_json={},
        )
    )
    db.commit()
    return {"status": "ok"}


@app.post("/api/admin/users")
async def create_admin_user(payload: AdminCreateRequest, user_ctx=Depends(get_current_user), db=Depends(db_session)):
    require_role(user_ctx, [UserRole.superadmin.value, UserRole.admin.value])
    existing = db.execute(select(User).where(User.email == payload.email)).scalar_one_or_none()
    target_role_raw = (payload.role or UserRole.admin.value).strip().lower()
    try:
        target_role = UserRole(target_role_raw)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid role") from exc
    if user_ctx["role"] == UserRole.admin.value and target_role != UserRole.manager:
        raise HTTPException(status_code=403, detail="Admins can only create managers")
    if target_role == UserRole.superadmin:
        raise HTTPException(status_code=400, detail="Cannot create superadmin via this endpoint")

    if existing:
        raise HTTPException(status_code=400, detail="Email already in use")
    has_tenant_id = bool(payload.tenant_id)
    has_new_tenant = bool(payload.new_tenant_name and payload.new_tenant_name.strip())
    if has_tenant_id == has_new_tenant:
        raise HTTPException(status_code=400, detail="Provide exactly one of tenant_id or new_tenant_name")

    tenant = None
    if has_tenant_id:
        tenant = db.get(Tenant, uuid.UUID(payload.tenant_id))
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")
        if user_ctx["role"] != UserRole.superadmin.value and str(tenant.id) not in get_accessible_tenant_ids(db, user_ctx):
            raise HTTPException(status_code=403, detail="Forbidden")
    else:
        tenant_name = payload.new_tenant_name.strip()
        existing_tenant = db.execute(select(Tenant).where(Tenant.name == tenant_name)).scalar_one_or_none()
        if existing_tenant:
            raise HTTPException(status_code=400, detail="Tenant name already in use")
        base_slug = _slugify(tenant_name)
        slug = base_slug
        suffix = 1
        while db.execute(select(Tenant).where(Tenant.slug == slug)).scalar_one_or_none():
            suffix += 1
            slug = f"{base_slug}-{suffix}"
        tenant = Tenant(name=tenant_name, slug=slug, status="active")
        db.add(tenant)
        db.flush()
        seed_quick_replies_for_tenant(db, tenant.id)
        if user_ctx["role"] == UserRole.admin.value:
            db.add(UserTenant(user_id=user_ctx["user"].id, tenant_id=tenant.id, membership_role="owner"))
        db.add(
            AuditLog(
                actor_user_id=user_ctx["user"].id,
                actor_role=user_ctx["role"],
                tenant_id=tenant.id,
                action="tenant_created",
                target_type="tenant",
                target_id=str(tenant.id),
                details_json={"name": tenant.name, "slug": tenant.slug},
            )
        )

    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        role=target_role,
        is_active=True,
    )
    db.add(user)
    db.flush()
    db.add(UserTenant(user_id=user.id, tenant_id=tenant.id, membership_role="admin"))
    db.add(
        AuditLog(
            actor_user_id=user_ctx["user"].id,
            actor_role=user_ctx["role"],
            tenant_id=tenant.id,
            action="user_created",
            target_type="user",
            target_id=str(user.id),
            details_json={"email": payload.email, "role": target_role.value},
        )
    )
    db.commit()
    return {"id": str(user.id), "email": user.email, "role": user.role.value, "tenant_id": str(tenant.id)}


@app.post("/api/admin/users/{user_id}/status")
async def update_user_status(user_id: str, payload: UserStatusRequest, user_ctx=Depends(get_current_user), db=Depends(db_session)):
    target_user = db.get(User, uuid.UUID(user_id))
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
    if target_user.role == UserRole.superadmin and user_ctx["role"] != UserRole.superadmin.value:
        raise HTTPException(status_code=403, detail="Cannot modify superadmin user")
    if user_ctx["role"] == UserRole.admin.value and target_user.role == UserRole.admin:
        raise HTTPException(status_code=403, detail="Admins cannot modify other admins")

    if user_ctx["role"] != UserRole.superadmin.value:
        actor_tenants = get_accessible_tenant_ids(db, user_ctx)
        membership = db.execute(select(UserTenant).where(UserTenant.user_id == target_user.id)).scalars().all()
        if not any(str(m.tenant_id) in actor_tenants for m in membership):
            raise HTTPException(status_code=403, detail="Forbidden")

    target_user.is_active = payload.is_active
    db.add(
        AuditLog(
            actor_user_id=user_ctx["user"].id,
            actor_role=user_ctx["role"],
            tenant_id=uuid.UUID(user_ctx["tenant_id"]) if user_ctx["tenant_id"] else None,
            action="user_status_updated",
            target_type="user",
            target_id=str(target_user.id),
            details_json={"is_active": payload.is_active},
        )
    )
    db.commit()
    return {"status": "ok", "user_id": str(target_user.id), "is_active": target_user.is_active}


@app.post("/api/admin/users/{user_id}/reset-password")
async def reset_user_password(user_id: str, payload: ResetPasswordRequest, user_ctx=Depends(get_current_user), db=Depends(db_session)):
    target_user = db.get(User, uuid.UUID(user_id))
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
    if target_user.role == UserRole.superadmin and user_ctx["role"] != UserRole.superadmin.value:
        raise HTTPException(status_code=403, detail="Cannot modify superadmin user")
    if user_ctx["role"] == UserRole.admin.value and target_user.role == UserRole.admin:
        raise HTTPException(status_code=403, detail="Admins cannot modify other admins")
    if user_ctx["role"] != UserRole.superadmin.value:
        actor_tenants = get_accessible_tenant_ids(db, user_ctx)
        membership = db.execute(select(UserTenant).where(UserTenant.user_id == target_user.id)).scalars().all()
        if not any(str(m.tenant_id) in actor_tenants for m in membership):
            raise HTTPException(status_code=403, detail="Forbidden")

    target_user.password_hash = hash_password(payload.new_password)
    db.add(
        AuditLog(
            actor_user_id=user_ctx["user"].id,
            actor_role=user_ctx["role"],
            tenant_id=uuid.UUID(user_ctx["tenant_id"]) if user_ctx["tenant_id"] else None,
            action="user_password_reset",
            target_type="user",
            target_id=str(target_user.id),
            details_json={},
        )
    )
    db.commit()
    return {"status": "ok", "user_id": str(target_user.id)}


@app.get("/api/admin/chats/{session_id}")
async def admin_chat_detail(session_id: str, user_ctx=Depends(get_current_user), db=Depends(db_session)):
    session = db.get(ChatSession, uuid.UUID(session_id))
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if user_ctx["role"] != UserRole.superadmin.value and str(session.tenant_id) not in get_accessible_tenant_ids(db, user_ctx):
        raise HTTPException(status_code=403, detail="Forbidden")
    messages = db.execute(
        select(ChatMessage).where(ChatMessage.session_id == session.id).order_by(ChatMessage.created_at.asc())
    ).scalars().all()
    message_ids = [m.id for m in messages]
    feedback_by_message = {}
    if message_ids:
        feedback_rows = db.execute(
            select(MessageFeedback.message_id, MessageFeedback.vote).where(MessageFeedback.message_id.in_(message_ids))
        ).all()
        for message_id, vote in feedback_rows:
            mid = str(message_id)
            if mid not in feedback_by_message:
                feedback_by_message[mid] = {"up": 0, "down": 0}
            if vote == FeedbackVote.up:
                feedback_by_message[mid]["up"] += 1
            elif vote == FeedbackVote.down:
                feedback_by_message[mid]["down"] += 1
    return [
        {
            "id": str(m.id),
            "sender_type": m.sender_type.value,
            "content": m.content,
            "created_at": m.created_at.isoformat(),
            "token_usage": m.token_usage_json or {},
            "feedback_summary": feedback_by_message.get(str(m.id), {"up": 0, "down": 0}),
        }
        for m in messages
    ]


@app.get("/api/admin/usage/summary")
async def admin_usage_summary(
    user_ctx=Depends(get_current_user),
    db=Depends(db_session),
    tenant_id: Optional[str] = Query(default=None),
):
    target_tenant_id = _resolve_effective_tenant_id_for_admin_views(db, user_ctx, tenant_id)

    usage_stmt = select(
        UsageEvent.usage_type,
        func.coalesce(func.sum(UsageEvent.prompt_tokens), 0),
        func.coalesce(func.sum(UsageEvent.completion_tokens), 0),
        func.coalesce(func.sum(UsageEvent.total_tokens), 0),
    )
    per_chat_stmt = select(
        UsageEvent.session_id,
        func.coalesce(func.sum(UsageEvent.total_tokens), 0),
    ).where(UsageEvent.session_id.is_not(None))
    per_tenant_stmt = select(
        UsageEvent.tenant_id,
        func.coalesce(func.sum(UsageEvent.total_tokens), 0),
    )

    tenant_uuid = uuid.UUID(target_tenant_id)
    usage_stmt = usage_stmt.where(UsageEvent.tenant_id == tenant_uuid)
    per_chat_stmt = per_chat_stmt.where(UsageEvent.tenant_id == tenant_uuid)
    per_tenant_stmt = per_tenant_stmt.where(UsageEvent.tenant_id == tenant_uuid)

    rows = db.execute(usage_stmt.group_by(UsageEvent.usage_type)).all()

    summary = {
        "chat_completion": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "chat_embedding": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "index_embedding": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }
    for usage_type, prompt_tokens, completion_tokens, total_tokens in rows:
        key = usage_type.value if hasattr(usage_type, "value") else str(usage_type)
        summary[key] = {
            "prompt_tokens": int(prompt_tokens or 0),
            "completion_tokens": int(completion_tokens or 0),
            "total_tokens": int(total_tokens or 0),
        }

    session_rows = db.execute(per_chat_stmt.group_by(UsageEvent.session_id)).all()
    per_chat = [{"session_id": str(sid), "total_tokens": int(tokens or 0)} for sid, tokens in session_rows if sid]
    per_chat.sort(key=lambda row: row["total_tokens"], reverse=True)

    tenant_rows = db.execute(per_tenant_stmt.group_by(UsageEvent.tenant_id)).all()
    per_tenant = [{"tenant_id": str(tid), "total_tokens": int(tokens or 0)} for tid, tokens in tenant_rows if tid]
    per_tenant.sort(key=lambda row: row["total_tokens"], reverse=True)

    return {
        "tenant_id": target_tenant_id,
        "scope": "tenant",
        "summary": summary,
        "embedding_total_tokens": int(summary["chat_embedding"]["total_tokens"] + summary["index_embedding"]["total_tokens"]),
        "per_chat_tokens": per_chat[:100],
        "per_tenant_tokens": per_tenant[:100],
    }


@app.get("/api/admin/overview")
async def admin_overview(
    user_ctx=Depends(get_current_user),
    db=Depends(db_session),
    tenant_id: Optional[str] = Query(default=None),
):
    target_tenant_id = _resolve_effective_tenant_id_for_admin_views(db, user_ctx, tenant_id)
    tenant_uuid = uuid.UUID(target_tenant_id)

    total_chats = db.execute(
        select(func.count(ChatSession.id)).where(ChatSession.tenant_id == tenant_uuid)
    ).scalar_one()

    unique_visitors = db.execute(
        select(func.count(func.distinct(ChatSession.visitor_id))).where(
            ChatSession.tenant_id == tenant_uuid,
            ChatSession.visitor_id.is_not(None),
        )
    ).scalar_one()

    likes = db.execute(
        select(func.count(MessageFeedback.id)).where(
            MessageFeedback.tenant_id == tenant_uuid,
            MessageFeedback.vote == FeedbackVote.up,
        )
    ).scalar_one()
    dislikes = db.execute(
        select(func.count(MessageFeedback.id)).where(
            MessageFeedback.tenant_id == tenant_uuid,
            MessageFeedback.vote == FeedbackVote.down,
        )
    ).scalar_one()

    token_rows = db.execute(
        select(
            UsageEvent.usage_type,
            func.coalesce(func.sum(UsageEvent.total_tokens), 0),
        ).where(UsageEvent.tenant_id == tenant_uuid).group_by(UsageEvent.usage_type)
    ).all()
    token_totals = {
        "chat_completion": 0,
        "chat_embedding": 0,
        "index_embedding": 0,
    }
    for usage_type, total_tokens in token_rows:
        key = usage_type.value if hasattr(usage_type, "value") else str(usage_type)
        token_totals[key] = int(total_tokens or 0)

    rating_rows = db.execute(
        select(
            func.count(SessionExperienceRating.id),
            func.coalesce(func.avg(SessionExperienceRating.rating), 0),
        ).where(SessionExperienceRating.tenant_id == tenant_uuid)
    ).one()
    rating_count = int(rating_rows[0] or 0)
    average_rating = float(rating_rows[1] or 0.0)

    return {
        "tenant_id": target_tenant_id,
        "total_chats": int(total_chats or 0),
        "unique_visitors": int(unique_visitors or 0),
        "embedding_token_usage": int(token_totals["chat_embedding"] + token_totals["index_embedding"]),
        "chat_token_usage": int(token_totals["chat_completion"]),
        "likes": int(likes or 0),
        "dislikes": int(dislikes or 0),
        "rating_count": rating_count,
        "average_rating": round(average_rating, 2),
    }


@app.post("/api/reindex")
async def trigger_reindex(request: ReindexRequest, user_ctx=Depends(get_current_user), db=Depends(db_session)):
    target_tenant_id = request.tenant_id or resolve_effective_tenant_id_for_admin_views(db, user_ctx, None)
    if not target_tenant_id:
        raise HTTPException(status_code=400, detail="Tenant ID required")
    if user_ctx["role"] != UserRole.superadmin.value and target_tenant_id not in get_accessible_tenant_ids(db, user_ctx):
        raise HTTPException(status_code=403, detail="Admins can only reindex own tenant")
    ensure_collection_for_tenant(target_tenant_id)
    scope = ReindexScope.all if user_ctx["role"] == UserRole.superadmin.value and request.tenant_id is None else ReindexScope.tenant
    job = ReindexJob(
        tenant_id=uuid.UUID(target_tenant_id) if scope == ReindexScope.tenant else None,
        triggered_by_user_id=user_ctx["user"].id,
        scope=scope,
        status="running",
        started_at=datetime.now(timezone.utc),
        meta_json={"target_tenant_id": target_tenant_id},
    )
    db.add(job)
    db.flush()
    db.add(
        AuditLog(
            actor_user_id=user_ctx["user"].id,
            actor_role=user_ctx["role"],
            tenant_id=job.tenant_id,
            action="reindex_triggered",
            target_type="tenant" if job.tenant_id else "global",
            target_id=target_tenant_id,
            details_json={"scope": scope.value},
        )
    )

    async def do_reindex(job_id: uuid.UUID):
        local_db = SessionLocal()
        local_job = local_db.get(ReindexJob, job_id)
        try:
            tenant = local_db.get(Tenant, uuid.UUID(target_tenant_id))

            def on_progress(progress: Dict[str, Any]):
                local_job.meta_json = {"target_tenant_id": target_tenant_id, "progress": progress}
                local_db.add(local_job)
                local_db.commit()

            def on_embedding_usage(usage: Dict[str, Any]):
                _record_usage_event(
                    local_db,
                    tenant_id=uuid.UUID(target_tenant_id),
                    usage_type=UsageType.index_embedding,
                    model_name=usage.get("model_name", ""),
                    prompt_tokens=usage.get("prompt_tokens", 0),
                    completion_tokens=usage.get("completion_tokens", 0),
                    total_tokens=usage.get("total_tokens", 0),
                    meta_json={"source": "reindex"},
                )
                local_db.commit()

            source_cfg = {}
            if tenant:
                source_cfg = _parse_source_dsn(
                    tenant.source_db_url,
                    tenant.source_table_prefix,
                    tenant.source_url_table,
                )
                source_cfg["source_mode"] = (tenant.source_mode or "").strip() or "wordpress"
                source_cfg["source_static_urls_json"] = tenant.source_static_urls_json
                source_cfg["source_domain_aliases"] = tenant.source_domain_aliases
                source_cfg["source_canonical_base_url"] = tenant.source_canonical_base_url
            payload_st = LEGACY_VECTOR_PRIMARY_SOURCE_TYPE
            payload_label = LEGACY_VECTOR_PRIMARY_SOURCE_LABEL
            url_fb = None
            if tenant:
                payload_st = (tenant.widget_source_type or "").strip() or LEGACY_VECTOR_PRIMARY_SOURCE_TYPE
                payload_label = (tenant.brand_name or tenant.name or "").strip() or LEGACY_VECTOR_PRIMARY_SOURCE_LABEL
                url_fb = (tenant.widget_website_url or "").strip() or None
            embedder = Embedder(
                client=qdrant_client,
                collection_name=_tenant_collection(target_tenant_id),
                source_config=source_cfg,
                progress_callback=on_progress,
                usage_callback=on_embedding_usage,
                vector_payload_source_type=payload_st,
                vector_payload_source_label=payload_label,
                url_fallback_base=url_fb,
            )
            await embedder.reindex_all_content()
            local_job.status = "completed"
            local_job.finished_at = datetime.now(timezone.utc)
            local_job.meta_json = {
                "target_tenant_id": target_tenant_id,
                "progress": embedder.get_indexing_status().get("progress", {}),
            }
            local_db.commit()
        except Exception as exc:
            local_job.status = "failed"
            local_job.error = str(exc)
            local_job.finished_at = datetime.now(timezone.utc)
            local_db.commit()
        finally:
            local_db.close()

    db.commit()
    asyncio.create_task(do_reindex(job.id))
    return {"job_id": str(job.id), "status": "started"}


@app.get("/api/reindex/jobs")
async def list_reindex_jobs(
    user_ctx=Depends(get_current_user),
    db=Depends(db_session),
    tenant_id: Optional[str] = Query(default=None),
):
    if user_ctx["role"] == UserRole.superadmin.value:
        jobs = db.execute(select(ReindexJob).order_by(ReindexJob.created_at.desc())).scalars().all()
        if tenant_id:
            jobs = [
                j for j in jobs
                if (j.tenant_id and str(j.tenant_id) == tenant_id)
                or (j.meta_json or {}).get("target_tenant_id") == tenant_id
            ]
    else:
        tenant_ids = get_accessible_tenant_ids(db, user_ctx)
        jobs = db.execute(
            select(ReindexJob).where(
                ReindexJob.tenant_id.in_([uuid.UUID(tid) for tid in tenant_ids])
            ).order_by(ReindexJob.created_at.desc())
        ).scalars().all() if tenant_ids else []
    tenant_ids = set()
    for j in jobs:
        if j.tenant_id:
            tenant_ids.add(str(j.tenant_id))
        target_tenant_id = (j.meta_json or {}).get("target_tenant_id")
        if target_tenant_id:
            tenant_ids.add(target_tenant_id)
    tenant_name_by_id = {}
    if tenant_ids:
        tenant_rows = db.execute(select(Tenant).where(Tenant.id.in_([uuid.UUID(tid) for tid in tenant_ids]))).scalars().all()
        tenant_name_by_id = {str(t.id): t.name for t in tenant_rows}
    return [
        {
            "id": str(j.id),
            "tenant_id": str(j.tenant_id) if j.tenant_id else None,
            "tenant_name": tenant_name_by_id.get(
                str(j.tenant_id) if j.tenant_id else (j.meta_json or {}).get("target_tenant_id")
            ),
            "status": j.status,
            "scope": j.scope.value,
            "created_at": j.created_at.isoformat() if j.created_at else None,
            "started_at": j.started_at.isoformat() if j.started_at else None,
            "finished_at": j.finished_at.isoformat() if j.finished_at else None,
            "error": j.error,
            "meta": j.meta_json or {},
        }
        for j in jobs
    ]

# Add a new endpoint for chunked reindexing with progress tracking
@app.post("/api/reindex-chunked")
async def trigger_chunked_reindex():
    """Trigger a chunked content reindexing with progress tracking"""
    try:
        # First check if Qdrant is accessible
        try:
            collections = qdrant_client.get_collections().collections
            logger.info(f"Successfully connected to Qdrant. Found {len(collections)} collections.")
        except Exception as e:
            logger.error(f"Error connecting to Qdrant before reindexing: {e}")
            raise HTTPException(
                status_code=503, 
                detail=f"Cannot connect to Qdrant database. Please ensure Qdrant is running: {e}"
            )
        
        # Create a simple progress callback that logs progress
        def progress_callback(message, current, total):
            logger.info(f"Progress: {message} ({current}/{total})")
        
        # Run reindexing with progress tracking
        embedder_instance = Embedder(client=qdrant_client)
        await embedder_instance.reindex_all_content(progress_callback)
        
        return {
            "status": "success", 
            "message": "Content reindexing completed successfully"
        }
    except HTTPException:
        # Re-raise HTTP exceptions as they already have proper status codes and details
        raise
    except Exception as e:
        logger.error(f"Error during reindexing: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to complete reindexing: {e}")

# Add global exception handler middleware
@app.middleware("http")
async def exception_handling_middleware(request: Request, call_next):
    try:
        response = await call_next(request)
        logger.info("%s %s -> %s", request.method, request.url.path, response.status_code)
        return response
    except Exception as e:
        logger.exception("Unhandled error for %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"}
        )


async def tenant_cors_enforcement_middleware(request: Request, call_next):
    origin = request.headers.get("origin")
    if not origin or not request.url.path.startswith("/api/"):
        return await call_next(request)
    is_public_api = request.url.path.startswith("/api/public/")

    tenant_obj: Optional[Tenant] = None
    x_widget_key = request.headers.get("x-widget-key")
    if x_widget_key:
        try:
            tenant_id = _resolve_embed_tenant_id(x_widget_key)
            with SessionLocal() as db:
                tenant_obj = db.get(Tenant, uuid.UUID(tenant_id))
        except Exception:
            # Do not fail middleware-level CORS on invalid widget key;
            # let the route return a proper auth error with CORS headers.
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

    if tenant_obj and not _tenant_origin_allowed(tenant_obj, origin):
        return JSONResponse(status_code=403, content={"detail": "Origin not allowed for tenant"})
    return await call_next(request)

# Run the app
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app:app",
        host=os.getenv("API_HOST", "0.0.0.0"), 
        port=int(os.getenv("API_PORT", 8043)),
        reload=False,
    ) 