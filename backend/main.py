import asyncio
import json
import logging
import os
import ipaddress
import re
import time
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import openai
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from qdrant_client import QdrantClient
from qdrant_client.http import models
from qdrant_client.http.models import Distance, VectorParams
from sqlalchemy import func, select
import geoip2.database
from geoip2.errors import AddressNotFoundError

from auth import create_access_token, decode_token, hash_password, verify_password
from core.policies import (
    get_accessible_tenant_ids,
    resolve_effective_tenant_id_for_admin_views,
)
from db import SessionLocal
from embedder import Embedder, LEGACY_VECTOR_PRIMARY_SOURCE_LABEL, LEGACY_VECTOR_PRIMARY_SOURCE_TYPE
from fuzzy_matcher import get_tenant_quick_reply, normalize_trigger_phrase, seed_quick_replies_for_tenant
from integrations.openai_client import OpenAIClientAdapter
from integrations.vector_store import VectorStoreAdapter
from indexing.payloads import build_result_context_payload
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
from retrieval.max_results import effective_chat_max_results, parse_explicit_result_cap
from retrieval.price_validation import has_invalid_price
from retrieval.planner import RetrievalPlan, apply_retrieval_rewrite, build_retrieval_plan
from retrieval.post_filter import (
    apply_score_threshold,
    catalog_match_mode_instruction,
    effective_score_threshold,
    filters_for_bucket,
)
from retrieval.hybrid import hybrid_search
from retrieval.tiered_search import execute_tiered_search
from indexing.collections import DENSE_VECTOR_NAME, collection_uses_hybrid_vectors
from retrieval.query_validator import validate_structured_query
from retrieval.catalog_response import (
    build_catalog_grounded_system_prompt,
    format_products_for_prompt,
)
from retrieval.filter_adherence import build_filter_adherence
from retrieval.query_understanding import QueryUnderstandingResult, run_query_understanding
from retrieval.catalog_cards import filter_results_for_catalog_cards, filter_results_for_response_sources
from retrieval.session_query import (
    is_session_reset_turn,
    load_structured_query_from_session,
    classify_merge_action,
    merge_session_query,
    SESSION_RESET_MESSAGE,
    structured_query_to_session_state,
    update_filter_stack,
)
from retrieval.trace import build_retrieval_trace, retrieval_debug_enabled
from retrieval.structured_query import StructuredQuery, empty_structured_query
from retrieval.chat_orchestrator import (
    apply_sort_to_results,
    build_static_response,
    classify_turn,
    ensure_commerce_catalog_intent,
    session_structured_query_for_writeback,
)
from retrieval.match_quality import classify_match_quality_for_results, finalize_response_subtype
from retrieval.response_composer import compose_search_intro
from retrieval.tools.product_refs import extract_product_title_from_message
from indexing.progress import normalize_reindex_progress
from retrieval.profile import apply_retrieval_profile_to_tenant, retrieval_profile_summary
from commerce.currency import currency_from_profile, normalize_currency_code
from sources.config import (
    coerce_source_mode_for_provider,
    normalize_source_provider,
    normalize_source_static_urls_json as shared_normalize_source_static_urls_json,
    parse_source_dsn as shared_parse_source_dsn,
    plan_to_dict,
    resolve_source_plan,
    resolve_vector_primary_source_type,
)
from url_utils import validate_and_fix_url, get_base_url
from tenant_assets import ensure_tenant_assets_dir, next_avatar_filename, remove_local_avatar_files_for_tenant, tenant_assets_dir
from services.public_security import (
    enforce_public_security_and_quota as _enforce_public_security_and_quota,
    extract_client_ip as _extract_client_ip,
    resolve_country_code_from_ip as _resolve_country_code_from_ip,
    utc_month_bounds as _utc_month_bounds,
)
from core.middleware import (
    effective_widget_origin as _effective_widget_origin,
    exception_handling_middleware,
    origin_allowed as _origin_allowed,
    tenant_cors_enforcement_middleware,
    tenant_origin_allowed as _tenant_origin_allowed,
)
from api.deps import (
    db_session,
    get_current_user,
    get_visitor_profile as _get_visitor_profile,
    get_visitor_profile_by_email as _get_visitor_profile_by_email,
    normalize_visitor_email as _normalize_visitor_email,
    normalize_visitor_id as _normalize_visitor_id,
    require_role,
    resolve_effective_tenant_id_for_admin_views as _resolve_effective_tenant_id_for_admin_views,
    resolve_embed_tenant_id as _resolve_embed_tenant_id,
    resolve_tenant_actor_user_id as _resolve_tenant_actor_user_id,
)
from api.schemas import (
    AdminCreateRequest,
    AuthRequest,
    AuthResponse,
    BlockedCountryRequest,
    BlockedIPRequest,
    BlockWordCategoryRequest,
    BlockWordRequest,
    ChatAction,
    ChatCategoryLink,
    ChatProduct,
    ChatRequest,
    ChatResponse,
    FeedbackRequest,
    GazetteerEntryMatchFlagsPatch,
    PublicSessionRatingRequest,
    PublicVisitorProfileRequest,
    QuickReplyCreateRequest,
    QuickReplyUpdateRequest,
    ReindexRequest,
    ResetPasswordRequest,
    RetrievalProfileGazetteerPatchRequest,
    SearchResult,
    TenantBrandingConfigRequest,
    TenantCreateRequest,
    TenantIdleRatingConfigRequest,
    TenantQuotaConfigRequest,
    TenantSourceConfigRequest,
    UserStatusRequest,
    UserTenantAssignRequest,
    UserTenantSetRequest,
)

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
logger = logging.getLogger("chatbot-api")

_SINGULAR_CHEAPEST_RE = re.compile(
    r"\b(?:what(?:'|\s+is)\s+the\s+cheapest|the\s+cheapest\s+(?:product|item))\b",
    re.IGNORECASE,
)

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


def _reindex_job_targets_tenant(job: ReindexJob, tenant_id: str) -> bool:
    if job.tenant_id and str(job.tenant_id) == tenant_id:
        return True
    return (job.meta_json or {}).get("target_tenant_id") == tenant_id


def _mark_interrupted_reindex_jobs_failed() -> int:
    session = SessionLocal()
    try:
        running_jobs = session.execute(
            select(ReindexJob).where(ReindexJob.status == "running").order_by(ReindexJob.created_at.desc())
        ).scalars().all()
        if not running_jobs:
            return 0
        now = datetime.now(timezone.utc)
        for job in running_jobs:
            meta = dict(job.meta_json or {})
            meta["recovered_on_startup"] = True
            job.status = "failed"
            job.error = job.error or "Reindex job interrupted by backend restart before completion."
            job.finished_at = now
            job.meta_json = meta
            session.add(job)
        session.commit()
        logger.warning("Marked %s interrupted reindex job(s) as failed during startup recovery", len(running_jobs))
        return len(running_jobs)
    except Exception:
        session.rollback()
        logger.exception("Failed to reconcile interrupted reindex jobs during startup")
        return 0
    finally:
        session.close()


@app.on_event("startup")
async def startup_event():
    global qdrant_client
    try:
        qdrant_client = _initialize_qdrant_client_with_retries()
    except Exception:
        qdrant_client = None
    _mark_interrupted_reindex_jobs_failed()
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


def _tenant_collection(tenant_id: str) -> str:
    return f"tenant_{tenant_id}_docs"


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "tenant"


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
    return shared_parse_source_dsn(dsn, table_prefix, url_table)


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
    return shared_normalize_source_static_urls_json(
        raw_value,
        domain_aliases=domain_aliases,
        canonical_base=canonical_base,
    )


def _provider_aware_source_config(tenant: Optional[Tenant]) -> Dict[str, Any]:
    source_cfg: Dict[str, Any] = {}
    if tenant:
        source_cfg = _parse_source_dsn(
            tenant.source_db_url,
            tenant.source_table_prefix,
            tenant.source_url_table,
        )
        source_cfg["source_db_url"] = tenant.source_db_url
        source_cfg["source_db_type"] = normalize_source_provider(
            tenant.source_db_type,
            source_mode=tenant.source_mode,
            source_db_url=tenant.source_db_url,
            source_static_urls_json=tenant.source_static_urls_json,
        )
        source_cfg["source_mode"] = (tenant.source_mode or "").strip() or "wordpress"
        source_cfg["source_static_urls_json"] = tenant.source_static_urls_json
        source_cfg["source_domain_aliases"] = tenant.source_domain_aliases
        source_cfg["source_canonical_base_url"] = tenant.source_canonical_base_url
        if source_cfg.get("source_db_type") == "magento":
            try:
                source_cfg["magento_store_id"] = int((tenant.source_url_table or "1").strip() or "1")
            except ValueError:
                source_cfg["magento_store_id"] = 1
    plan = resolve_source_plan(source_cfg)
    source_cfg.update(plan_to_dict(plan))
    return source_cfg


def _get_chat_session_state(session: ChatSession) -> Dict[str, Any]:
    filters_blob = session.active_filters_json or {}
    structured = None
    filter_stack: list[dict[str, Any]] = []
    recent_requests: list[str] = []
    if isinstance(filters_blob, dict):
        if isinstance(filters_blob.get("structured_query"), dict):
            structured = filters_blob["structured_query"]
            filter_stack = list(filters_blob.get("filter_stack") or [])
            recent_requests = list(filters_blob.get("recent_requests") or [])
        elif filters_blob.get("intent") and "free_text" in filters_blob:
            structured = filters_blob
    return {
        "conversation_summary": session.conversation_summary or "",
        "active_filters": filters_blob if not structured else {},
        "structured_query": structured,
        "filter_stack": filter_stack,
        "user_preferences": session.user_preferences_json or {},
        "last_result_context": session.last_result_context_json or [],
        "conversation_intent": session.conversation_intent or "general",
        "recent_requests": recent_requests,
    }


def _set_chat_session_state(session: ChatSession, state: Dict[str, Any]) -> None:
    session.conversation_summary = state.get("conversation_summary") or None
    if state.get("structured_query") is not None:
        session.active_filters_json = {
            "structured_query": state.get("structured_query") or {},
            "filter_stack": list(state.get("filter_stack") or []),
            "recent_requests": list(state.get("recent_requests") or []),
        }
    else:
        session.active_filters_json = state.get("active_filters") or {}
    session.user_preferences_json = state.get("user_preferences") or {}
    session.last_result_context_json = state.get("last_result_context") or []
    session.conversation_intent = state.get("conversation_intent") or None


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
    from indexing.collections import ensure_hybrid_collection, ensure_legacy_dense_collection
    from indexing.sparse import sparse_indexing_enabled

    if sparse_indexing_enabled():
        if not ensure_hybrid_collection(qdrant_client, collection_name, recreate=False):
            ensure_legacy_dense_collection(qdrant_client, collection_name)
    else:
        collection_names = [c.name for c in qdrant_client.get_collections().collections]
        if collection_name not in collection_names:
            ensure_legacy_dense_collection(qdrant_client, collection_name)
    index_fields = [
        ("source_provider", models.PayloadSchemaType.KEYWORD),
        ("content_kind", models.PayloadSchemaType.KEYWORD),
        ("content_bucket", models.PayloadSchemaType.KEYWORD),
        ("entity_id", models.PayloadSchemaType.KEYWORD),
        ("brand", models.PayloadSchemaType.KEYWORD),
        ("stock_status", models.PayloadSchemaType.KEYWORD),
        ("categories", models.PayloadSchemaType.KEYWORD),
        ("price", models.PayloadSchemaType.FLOAT),
    ]
    for field_name, field_schema in index_fields:
        try:
            qdrant_client.create_payload_index(
                collection_name=collection_name,
                field_name=field_name,
                field_schema=field_schema,
            )
        except Exception:
            continue

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
    preferred_buckets: Optional[List[str]] = None,
    metadata_filters: Optional[Dict[str, Any]] = None,
    content_kind: Optional[str] = None,
    use_hybrid: bool = False,
    lexical_text: Optional[str] = None,
    *,
    catalog_buckets_only: bool = False,
) -> List[Any]:
    if qdrant_client is None:
        raise HTTPException(status_code=503, detail="Qdrant service is unavailable")
    collection_name = _tenant_collection(tenant_id)
    primary_st = (primary_source_type or "").strip() or None

    try:
        vector_store = VectorStoreAdapter(qdrant_client)
        named_dense = collection_uses_hybrid_vectors(qdrant_client, collection_name)
        ordered_buckets = preferred_buckets or ["cms", "support", "catalog", "static"]
        if catalog_buckets_only:
            ordered_buckets = ["catalog"]

        def _collect_bucket_hits(*, source_type: str | None) -> list[Any]:
            collected: list[Any] = []
            seen: set[Any] = set()
            for bucket in ordered_buckets:
                bucket_filters = filters_for_bucket(metadata_filters, bucket)
                if use_hybrid and bucket == "catalog":
                    bucket_results = hybrid_search(
                        qdrant_client,
                        collection_name=collection_name,
                        dense_vector=embedding,
                        lexical_text=lexical_text or "",
                        limit=limit,
                        source_type=source_type,
                        content_bucket=bucket,
                        content_kind=content_kind,
                        metadata_filters=bucket_filters or None,
                    )
                else:
                    bucket_results = vector_store.search(
                        collection_name=collection_name,
                        query_vector=embedding,
                        limit=limit,
                        source_type=source_type,
                        content_bucket=bucket,
                        content_kind=content_kind if bucket == "catalog" else None,
                        metadata_filters=bucket_filters or None,
                        vector_name=DENSE_VECTOR_NAME if named_dense else None,
                    )
                for result in bucket_results:
                    result_id = result.payload.get("entity_id") or getattr(result, "id", None)
                    if result_id in seen:
                        continue
                    seen.add(result_id)
                    collected.append(result)
                    if len(collected) >= limit:
                        break
                if len(collected) >= limit:
                    break
            return collected

        all_results = _collect_bucket_hits(source_type=primary_st)
        if not all_results and primary_st:
            all_results = _collect_bucket_hits(source_type=None)
        if not catalog_buckets_only and len(all_results) < limit:
            seen_ids = {r.payload.get("entity_id") or getattr(r, "id", None) for r in all_results}
            external_results = vector_store.search(
                collection_name=collection_name,
                query_vector=embedding,
                source_type="external",
                limit=limit,
                vector_name=DENSE_VECTOR_NAME if named_dense else None,
            )
            for result in external_results:
                result_id = result.payload.get("entity_id") or getattr(result, "id", None)
                if result_id in seen_ids:
                    continue
                seen_ids.add(result_id)
                all_results.append(result)
                if len(all_results) >= limit:
                    break
        all_results.sort(key=lambda x: x.score, reverse=True)
        return all_results[:limit]
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


def _tenant_retrieval_profile(tenant_row: Optional[Tenant]) -> Optional[dict[str, Any]]:
    if not tenant_row or not tenant_row.retrieval_profile_json:
        return None
    profile = tenant_row.retrieval_profile_json
    return profile if isinstance(profile, dict) else None


def _tenant_currency(
    tenant_row: Optional[Tenant],
    profile: Optional[dict[str, Any]] = None,
) -> str:
    prof = profile if profile is not None else _tenant_retrieval_profile(tenant_row)
    return currency_from_profile(prof)


def _with_currency_meta(meta: Optional[dict[str, Any]], currency: str) -> dict[str, Any]:
    merged = dict(meta or {})
    merged.setdefault("currency", currency)
    return merged


def _resolve_website_url(
    tenant_row: Optional[Tenant],
    results: list[Any] | None = None,
) -> str | None:
    if tenant_row and (tenant_row.widget_website_url or "").strip():
        return tenant_row.widget_website_url.strip()
    for result in results or []:
        payload = getattr(result, "payload", None) or {}
        url = (payload.get("url") or "").strip()
        if url:
            base = get_base_url(url)
            if base:
                return base
    return None


async def _apply_turn_adequacy(
    *,
    message: str,
    answer: str,
    response_subtype: str | None,
    classification: Any,
    products: list[ChatProduct] | None,
    actions: list[dict[str, Any]] | None,
    website_url: str | None,
    structured_query_intent: str | None,
    meta: dict[str, Any] | None,
) -> tuple[str, list[ChatProduct] | None, list[dict[str, Any]] | None, str | None, dict[str, Any]]:
    from retrieval.turn_adequacy import apply_turn_adequacy

    adequacy = await apply_turn_adequacy(
        user_message=message,
        answer=answer,
        response_subtype=response_subtype,
        browse_all=bool(getattr(classification, "browse_all", False)),
        products=products,
        actions=actions,
        website_url=website_url,
        structured_query_intent=structured_query_intent,
        llm_call=openai_adapter.create_structured_completion,
    )
    merged_meta = dict(meta or {})
    merged_meta.update(adequacy.meta)
    return (
        adequacy.answer,
        products,
        adequacy.actions,
        adequacy.response_subtype or response_subtype,
        merged_meta,
    )


def _build_chat_system_prompt(
    tenant_row: Optional[Tenant],
    *,
    intent: str = "general",
    match_mode: Optional[str] = None,
) -> str:
    """Tenant-aware system prompt for final answer generation."""
    brand = _tenant_chat_brand_label(tenant_row)
    site = (tenant_row.widget_website_url or "").strip() if tenant_row else ""
    site_clause = (
        f" Official website (for grounding references only): {site}."
        if site
        else ""
    )
    if intent == "catalog":
        mode_note = catalog_match_mode_instruction(match_mode) if match_mode and match_mode != "exact" else ""
        mode_clause = f" {mode_note}" if mode_note else ""
        return (
            f"You are a shopping assistant for {brand}. The context lists products from the catalog. "
            "Recommend specific products from the context with name, price when available, and mention they can open the link. "
            "Do not tell the user to search the website when matching products are already in the context."
            f"{mode_clause}"
            f"{site_clause} "
            "Keep responses concise and under 300 characters."
        )
    return (
        f"You are a helpful assistant for {brand}. Use only the provided context snippets to answer; "
        f"if the context does not contain the answer, say so briefly and suggest checking the website or contacting the team."
        f"{site_clause} "
        "Keep responses concise and under 250 characters when a short reply suffices."
    )


def _build_chat_products(
    filtered_results: list[Any],
    match_scores: list[Any] | None = None,
) -> list[ChatProduct]:
    from retrieval.catalog_cards import is_product_card_eligible

    products: list[ChatProduct] = []
    seen_entities: set[str] = set()
    for index, result in enumerate(filtered_results):
        payload = result.payload or {}
        if not is_product_card_eligible(payload):
            continue
        entity_id = str(payload.get("entity_id") or "")
        if entity_id and entity_id in seen_entities:
            continue
        if entity_id:
            seen_entities.add(entity_id)
        title = (payload.get("title") or "").strip() or "Product"
        url = (payload.get("url") or "").strip()
        if not url:
            continue
        price_raw = payload.get("price")
        price_val = float(price_raw) if price_raw not in (None, "") else None
        rating_raw = payload.get("rating")
        rating_val = float(rating_raw) if rating_raw not in (None, "") else None
        review_raw = payload.get("review_count")
        review_val = int(review_raw) if review_raw not in (None, "") else None
        mq = None
        missed = None
        if match_scores and index < len(match_scores):
            mq = match_scores[index].match_quality
            missed = list(match_scores[index].missed_constraints or []) or None
        currency_val = None
        currency_raw = payload.get("currency")
        if currency_raw not in (None, ""):
            currency_val = normalize_currency_code(str(currency_raw))
        products.append(
            ChatProduct(
                title=title,
                url=url,
                price=price_val,
                brand=(payload.get("brand") or None),
                image_url=payload.get("image_url"),
                score=result.score,
                rating=rating_val,
                review_count=review_val,
                match_quality=mq,
                missed_constraints=missed,
                currency=currency_val,
            )
        )
    return products


async def _resolve_structured_query(
    message: str,
    session_state: Dict[str, Any],
    profile: Optional[dict[str, Any]],
) -> tuple[StructuredQuery, RetrievalPlan, QueryUnderstandingResult, Optional[Dict[str, Any]], list[dict[str, Any]]]:
    session_query = load_structured_query_from_session(session_state)
    conversation_summary = (session_state.get("conversation_summary") or "").strip() or None
    understanding = await run_query_understanding(
        message,
        profile,
        session_query,
        llm_call=openai_adapter.create_structured_completion,
        conversation_summary=conversation_summary,
    )
    validation_started = time.perf_counter()
    turn_validated = validate_structured_query(understanding.query, profile=profile)
    filter_stack = list(session_state.get("filter_stack") or [])
    merged = merge_session_query(
        session_query,
        turn_validated,
        user_message=message,
        filter_stack=filter_stack,
    )
    merge_action = classify_merge_action(session_query, turn_validated, user_message=message)
    filter_stack = update_filter_stack(
        filter_stack,
        before=session_query,
        after=merged,
        merge_action=merge_action,
    )
    merged = validate_structured_query(merged, profile=profile)
    merged = apply_retrieval_rewrite(merged)
    understanding.validation_ms = (time.perf_counter() - validation_started) * 1000.0
    plan = build_retrieval_plan(merged, profile=profile, tenant_profile=profile)
    debug_ctx: Optional[Dict[str, Any]] = None
    if retrieval_debug_enabled():
        debug_ctx = {
            "session_query": session_query,
            "turn_after_qu": understanding.query,
            "turn_after_validate": turn_validated,
            "conversation_summary": conversation_summary,
        }
    return merged, plan, understanding, debug_ctx, filter_stack


def _catalog_skip_preprocess() -> bool:
    return os.getenv("RETRIEVAL_CATALOG_SKIP_PREPROCESS", "true").strip().lower() in ("1", "true", "yes")


def _search_limit_for_plan(max_hits: int, plan: RetrievalPlan) -> int:
    multiplier = max(1, int(os.getenv("RETRIEVAL_SEARCH_LIMIT_MULTIPLIER", "5")))
    cap = max(1, int(os.getenv("CHAT_MAX_RESULTS_ABSOLUTE_CEILING", "50")))
    if plan.facet_excludes:
        try:
            exclude_multiplier = max(2, int(os.getenv("RETRIEVAL_FACET_EXCLUDE_SEARCH_MULTIPLIER", "3")))
        except ValueError:
            exclude_multiplier = 3
        multiplier = max(multiplier, multiplier * exclude_multiplier)
    if (
        plan.price_min is not None
        or plan.price_max is not None
        or plan.metadata_filters
        or plan.category_hint_terms
        or plan.facet_excludes
    ):
        return min(max(max_hits * multiplier, max_hits), cap)
    return max_hits


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
    catalog_products_json: Optional[str] = None,
) -> tuple[str, Dict[str, Any]]:
    try:
        sys_msg = system_prompt or _DEFAULT_GENERATE_ANSWER_SYSTEM_PROMPT
        if catalog_products_json:
            user_content = f"Question: {query}\n\nproducts:\n{catalog_products_json}"
        else:
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
            user_content = f"Question: {query}\n\nContext: {context}"

        response = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": sys_msg},
                {"role": "user", "content": user_content},
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
    vector_primary_source_type = (
        resolve_vector_primary_source_type(
            widget_source_type=tenant_row.widget_source_type,
            source_db_type=tenant_row.source_db_type,
            source_mode=tenant_row.source_mode,
            source_db_url=tenant_row.source_db_url,
            source_static_urls_json=tenant_row.source_static_urls_json,
        )
        if tenant_row
        else None
    )
    url_fallback = ((tenant_row.widget_website_url or "").strip() or None) if tenant_row else None
    message_cap = parse_explicit_result_cap(request.message)
    request_cap = request.max_results if request.max_results is not None else message_cap
    max_hits = effective_chat_max_results(tenant=tenant_row, request_max=request_cap)

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
            _set_chat_session_state(session, _get_chat_session_state(session))

    db.add(
        ChatMessage(
            session_id=session.id,
            tenant_id=session.tenant_id,
            sender_type=SenderType.user,
            content=request.message,
            model_name="",
        )
    )
    session_state = _get_chat_session_state(session)
    retrieval_profile = _tenant_retrieval_profile(tenant_row)
    tenant_currency = _tenant_currency(tenant_row, retrieval_profile)

    fuzzy_response = get_tenant_quick_reply(db, tenant_id, request.message, tenant_row)
    if fuzzy_response:
        session_query = load_structured_query_from_session(session_state)
        session_state = structured_query_to_session_state(
            structured_query=session_query,
            user_message=request.message,
            result_context=[],
            recent_requests=list(session_state.get("recent_requests") or []),
        )
        _set_chat_session_state(session, session_state)
        assistant_message = ChatMessage(
            session_id=session.id,
            tenant_id=session.tenant_id,
            sender_type=SenderType.assistant,
            content=fuzzy_response["response"],
            model_name="fuzzy-match",
            token_usage_json={"model_name": "fuzzy-match"},
        )
        db.add(assistant_message)
        session.last_message_at = datetime.now(timezone.utc)
        db.commit()
        return ChatResponse(
            response=fuzzy_response["response"],
            session_id=str(session.id),
            message_id=str(assistant_message.id),
            source="fuzzy",
            confidence=fuzzy_response.get("confidence", 1.0),
            sources=[],
            products=None,
            retrieval_tier=None,
            match_mode=None,
            meta={"currency": tenant_currency},
        )

    structured_query, retrieval_plan, query_understanding, retrieval_debug_ctx, filter_stack = (
        await _resolve_structured_query(
            request.message,
            session_state,
            retrieval_profile,
        )
    )

    classification = classify_turn(
        request.message,
        structured_query=structured_query,
        session_state=session_state,
        profile=retrieval_profile,
    )
    pre_intent = structured_query.intent
    structured_query = ensure_commerce_catalog_intent(structured_query, classification)
    if structured_query.intent == "catalog" and pre_intent != "catalog":
        structured_query = apply_retrieval_rewrite(structured_query)
        retrieval_plan = build_retrieval_plan(
            structured_query,
            profile=retrieval_profile,
            tenant_profile=retrieval_profile,
        )
    if classification.sort:
        structured_query.sort = classification.sort
        structured_query = apply_retrieval_rewrite(structured_query)
        retrieval_plan = build_retrieval_plan(
            structured_query,
            profile=retrieval_profile,
            tenant_profile=retrieval_profile,
        )

    if classification.preserve_catalog_session and classification.response_subtype == "product_search":
        prior_blob = session_state.get("structured_query") or {}
        if prior_blob.get("category", {}).get("values") or prior_blob.get("facets") or prior_blob.get("price", {}).get("max"):
            structured_query = validate_structured_query(
                StructuredQuery.from_dict(prior_blob),
                profile=retrieval_profile,
            )
            structured_query = apply_retrieval_rewrite(structured_query)
            retrieval_plan = build_retrieval_plan(
                structured_query,
                profile=retrieval_profile,
                tenant_profile=retrieval_profile,
            )

    brand_label = _tenant_chat_brand_label(tenant_row)
    website_url = ((tenant_row.widget_website_url or "").strip() or None) if tenant_row else None

    if has_invalid_price(structured_query):
        static_extras = build_static_response(
            request.message,
            classification=classification,
            structured_query=structured_query,
            session_state=session_state,
            profile=retrieval_profile,
            brand=brand_label,
            website_url=website_url,
        )
        if static_extras and static_extras.skip_catalog_llm:
            write_sq = session_structured_query_for_writeback(
                structured_query=structured_query,
                session_state=session_state,
                classification=classification,
            )
            session_state = structured_query_to_session_state(
                structured_query=write_sq,
                user_message=request.message,
                result_context=[],
                recent_requests=list(session_state.get("recent_requests") or []),
                filter_stack=filter_stack,
            )
            static_answer, _, static_actions, static_subtype, static_meta = await _apply_turn_adequacy(
                message=request.message,
                answer=static_extras.intro_text,
                response_subtype=static_extras.response_subtype,
                classification=classification,
                products=None,
                actions=static_extras.actions,
                website_url=website_url,
                structured_query_intent=structured_query.intent,
                meta=_with_currency_meta(static_extras.meta, tenant_currency),
            )
            assistant_message = ChatMessage(
                session_id=session.id,
                tenant_id=session.tenant_id,
                sender_type=SenderType.assistant,
                content=static_answer,
                model_name="commerce-router",
                token_usage_json={"model_name": "commerce-router", "response_subtype": static_subtype},
            )
            db.add(assistant_message)
            session.last_message_at = datetime.now(timezone.utc)
            _set_chat_session_state(session, session_state)
            db.commit()
            return ChatResponse(
                response=static_answer,
                session_id=str(session.id),
                message_id=str(assistant_message.id),
                source="commerce_router",
                confidence=1.0,
                categories=[ChatCategoryLink(**c) for c in static_extras.categories] if static_extras.categories else None,
                actions=[ChatAction(**a) for a in static_actions] if static_actions else None,
                meta=static_meta,
                response_subtype=static_subtype,
            )

    _NO_SEARCH_SUBTYPES = frozenset({"list_categories", "general_chat", "guided_discovery", "not_in_catalog"})
    if classification.response_subtype in _NO_SEARCH_SUBTYPES:
        static_extras = build_static_response(
            request.message,
            classification=classification,
            structured_query=structured_query,
            session_state=session_state,
            profile=retrieval_profile,
            brand=brand_label,
            website_url=website_url,
        )
        if static_extras and static_extras.skip_catalog_llm:
            write_sq = session_structured_query_for_writeback(
                structured_query=structured_query,
                session_state=session_state,
                classification=classification,
            )
            session_state = structured_query_to_session_state(
                structured_query=write_sq,
                user_message=request.message,
                result_context=[],
                recent_requests=list(session_state.get("recent_requests") or []),
                filter_stack=filter_stack,
            )
            static_answer, _, static_actions, static_subtype, static_meta = await _apply_turn_adequacy(
                message=request.message,
                answer=static_extras.intro_text,
                response_subtype=static_extras.response_subtype,
                classification=classification,
                products=None,
                actions=static_extras.actions,
                website_url=website_url,
                structured_query_intent=structured_query.intent,
                meta=_with_currency_meta(static_extras.meta, tenant_currency),
            )
            assistant_message = ChatMessage(
                session_id=session.id,
                tenant_id=session.tenant_id,
                sender_type=SenderType.assistant,
                content=static_answer,
                model_name="commerce-router",
                token_usage_json={"model_name": "commerce-router", "response_subtype": static_subtype},
            )
            db.add(assistant_message)
            session.last_message_at = datetime.now(timezone.utc)
            _set_chat_session_state(session, session_state)
            db.commit()
            return ChatResponse(
                response=static_answer,
                session_id=str(session.id),
                message_id=str(assistant_message.id),
                source="commerce_router",
                confidence=1.0,
                categories=[ChatCategoryLink(**c) for c in static_extras.categories] if static_extras.categories else None,
                actions=[ChatAction(**a) for a in static_actions] if static_actions else None,
                meta=static_meta,
                response_subtype=static_subtype,
            )

    if is_session_reset_turn(request.message, structured_query):
        cleared = empty_structured_query(intent="general")
        session_state = structured_query_to_session_state(
            structured_query=cleared,
            user_message=request.message,
            result_context=[],
            recent_requests=[],
        )
        _set_chat_session_state(session, session_state)
        assistant_message = ChatMessage(
            session_id=session.id,
            tenant_id=session.tenant_id,
            sender_type=SenderType.assistant,
            content=SESSION_RESET_MESSAGE,
            model_name="session-reset",
            token_usage_json={"model_name": "session-reset"},
        )
        db.add(assistant_message)
        session.last_message_at = datetime.now(timezone.utc)
        db.commit()
        return ChatResponse(
            response=SESSION_RESET_MESSAGE,
            session_id=str(session.id),
            message_id=str(assistant_message.id),
            source="session_reset",
            confidence=1.0,
            sources=[],
            products=None,
            retrieval_tier=None,
            match_mode=None,
            meta={"currency": tenant_currency},
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

    products: list[ChatProduct] = []
    retrieval_tier: Optional[str] = None
    match_mode: Optional[str] = None
    commerce_categories: list[dict[str, Any]] = []
    commerce_actions: list[dict[str, Any]] = []
    commerce_meta: dict[str, Any] = {"currency": tenant_currency}
    response_subtype: str = classification.response_subtype
    match_scores: list[Any] = []
    if qdrant_client is None:
        raise HTTPException(status_code=503, detail="Qdrant unavailable")
    if classification.response_subtype == "product_detail":
        title_hint = extract_product_title_from_message(request.message)
        if title_hint:
            from retrieval.structured_query import CategorySpec

            structured_query = structured_query.copy()
            structured_query.category = CategorySpec()
            structured_query.free_text = title_hint
            structured_query = apply_retrieval_rewrite(structured_query)
            retrieval_plan = build_retrieval_plan(
                structured_query,
                profile=retrieval_profile,
                tenant_profile=retrieval_profile,
            )
            retrieval_plan = replace(
                retrieval_plan,
                dense_query_text=title_hint,
                lexical_query_text=title_hint,
            )
    query_for_embedding = retrieval_plan.dense_query_text or request.message
    if structured_query.intent == "catalog" and _catalog_skip_preprocess():
        enhanced_query = query_for_embedding
    else:
        enhanced_query = await preprocess_query(
            query_for_embedding,
            tenant_brand_name=_tenant_chat_brand_label(tenant_row),
            tenant_website_url=((tenant_row.widget_website_url or "").strip() or None) if tenant_row else None,
        )
    embedding, embedding_usage = await generate_embedding(enhanced_query)
    search_limit = _search_limit_for_plan(max_hits, retrieval_plan)

    async def _tier_search_fn(filters: dict[str, Any]) -> list[Any]:
        return await search_qdrant(
            tenant_id,
            embedding,
            search_limit,
            primary_source_type=vector_primary_source_type,
            preferred_buckets=retrieval_plan.preferred_buckets,
            metadata_filters=filters or None,
            content_kind=retrieval_plan.content_kind,
            use_hybrid=retrieval_plan.use_retrieval_hybrid,
            lexical_text=retrieval_plan.lexical_query_text,
            catalog_buckets_only=structured_query.intent == "catalog",
        )

    tiered = await execute_tiered_search(
        _tier_search_fn,
        plan=retrieval_plan,
        profile=retrieval_profile,
        intent=structured_query.intent,
    )
    search_results = tiered.hits
    retrieval_tier = tiered.tier
    match_mode = tiered.match_mode
    score_threshold = effective_score_threshold(
        plan=retrieval_plan,
        structured_query=structured_query,
        tier=tiered.tier,
    )
    filtered_results = apply_score_threshold(
        search_results,
        threshold=score_threshold,
        max_hits=max_hits,
    )
    from retrieval.post_filter import boost_results_by_rating
    from retrieval.response_contract import rating_boost_weight

    filtered_results = boost_results_by_rating(
        filtered_results,
        weight=rating_boost_weight(retrieval_profile),
    )
    if structured_query.min_rating is not None:
        from retrieval.post_filter import filter_results_by_min_rating

        filtered_results = filter_results_by_min_rating(
            filtered_results,
            min_rating=structured_query.min_rating,
        )
    card_results = (
        filter_results_for_catalog_cards(filtered_results)
        if structured_query.intent == "catalog"
        else []
    )
    if structured_query.min_rating is not None and card_results:
        from retrieval.post_filter import filter_results_by_min_rating

        card_results = filter_results_by_min_rating(
            card_results,
            min_rating=structured_query.min_rating,
        )
    if structured_query.intent == "catalog" and (classification.sort or structured_query.sort):
        card_results = apply_sort_to_results(card_results, structured_query, classification)[:max_hits]
    if structured_query.intent == "catalog" and _SINGULAR_CHEAPEST_RE.search(request.message or ""):
        card_results = card_results[:1]

    website_url = _resolve_website_url(tenant_row, card_results or filtered_results) or website_url

    post_search_static = build_static_response(
        request.message,
        classification=classification,
        structured_query=structured_query,
        session_state=session_state,
        profile=retrieval_profile,
        brand=brand_label,
        website_url=website_url,
        card_results=card_results,
        search_results=filtered_results,
    )
    if post_search_static and post_search_static.skip_catalog_llm:
        write_sq = session_structured_query_for_writeback(
            structured_query=structured_query,
            session_state=session_state,
            classification=classification,
        )
        session_state = structured_query_to_session_state(
            structured_query=write_sq,
            user_message=request.message,
            result_context=[],
            recent_requests=list(session_state.get("recent_requests") or []),
            filter_stack=filter_stack,
        )
        static_products = None
        if post_search_static.products:
            static_products = [ChatProduct(**p) for p in post_search_static.products]
        elif post_search_static.response_subtype == "category_plp_sample" and card_results:
            static_products = _build_chat_products(card_results)
        static_answer, static_products, static_actions, static_subtype, static_meta = await _apply_turn_adequacy(
            message=request.message,
            answer=post_search_static.intro_text,
            response_subtype=post_search_static.response_subtype,
            classification=classification,
            products=static_products,
            actions=post_search_static.actions,
            website_url=website_url,
            structured_query_intent=structured_query.intent,
            meta=_with_currency_meta(post_search_static.meta, tenant_currency),
        )
        assistant_message = ChatMessage(
            session_id=session.id,
            tenant_id=session.tenant_id,
            sender_type=SenderType.assistant,
            content=static_answer,
            model_name="commerce-router",
            token_usage_json={
                "model_name": "commerce-router",
                "response_subtype": static_subtype,
            },
        )
        db.add(assistant_message)
        session.last_message_at = datetime.now(timezone.utc)
        _set_chat_session_state(session, session_state)
        db.commit()
        return ChatResponse(
            response=static_answer,
            session_id=str(session.id),
            message_id=str(assistant_message.id),
            source="commerce_router",
            confidence=1.0,
            products=static_products,
            categories=[ChatCategoryLink(**c) for c in post_search_static.categories]
            if post_search_static.categories
            else None,
            actions=[ChatAction(**a) for a in static_actions] if static_actions else None,
            meta=static_meta,
            response_subtype=static_subtype,
        )

    commerce_intro = ""
    if structured_query.intent == "catalog" and card_results:
        card_results, match_scores = classify_match_quality_for_results(
            card_results,
            structured_query=structured_query,
            user_message=request.message,
            profile=retrieval_profile,
            category_hint_terms=list(retrieval_plan.category_hint_terms or []),
            price_relaxed=tiered.price_relaxed,
            retrieval_tier=retrieval_tier,
        )
        response_subtype = finalize_response_subtype(
            match_scores,
            base_subtype=classification.response_subtype,
        )
        commerce_intro = compose_search_intro(
            scores=match_scores,
            response_subtype=response_subtype,
            price_max=structured_query.price.max,
            price_min=structured_query.price.min,
            validation_meta=structured_query.validation_meta,
            currency_code=tenant_currency,
        )
        commerce_meta["loader_stage"] = commerce_meta.get("loader_stage") or response_subtype
        plp_static = build_static_response(
            request.message,
            classification=classification,
            structured_query=structured_query,
            session_state=session_state,
            profile=retrieval_profile,
            brand=brand_label,
            website_url=website_url,
            card_results=card_results,
        )
        if plp_static:
            if plp_static.actions:
                commerce_actions = plp_static.actions
            if plp_static.intro_text and classification.response_subtype in (
                "category_plp_sample",
                "category_availability",
                "sort_browse",
            ):
                commerce_intro = plp_static.intro_text or commerce_intro
            if plp_static.meta:
                commerce_meta.update(plp_static.meta)
            if plp_static.response_subtype in ("category_plp_sample", "sort_browse", "category_availability"):
                response_subtype = plp_static.response_subtype
    catalog_products_only = structured_query.intent == "catalog"
    if catalog_products_only and card_results:
        response_results = card_results
    else:
        response_results = filter_results_for_response_sources(
            filtered_results,
            structured_query.intent,
        )
    filter_adherence: Dict[str, Any] | None = None
    if structured_query.intent == "catalog":
        catalog_hit_count = len(filtered_results) or len(search_results)
        filter_adherence = build_filter_adherence(
            user_message=request.message,
            structured_query=structured_query,
            retrieval_plan=retrieval_plan,
            card_results=card_results,
            profile=retrieval_profile,
            match_mode=match_mode,
            retrieval_tier=retrieval_tier,
            dropped_filters=list(tiered.dropped_filters or []),
            hit_count=catalog_hit_count,
            product_card_count=len(card_results),
            price_relaxed=tiered.price_relaxed,
        )

    embedding_meta: Dict[str, Any] = {
        "source": "chat_query",
        "intent": structured_query.intent,
        "retrieval_tier": retrieval_tier,
        "match_mode": match_mode,
        "dropped_filters": tiered.dropped_filters,
        "query_understanding_mode": query_understanding.mode,
        "rules_prepass_ms": query_understanding.prepass_ms,
        "llm_ms": query_understanding.llm_ms,
        "validation_ms": query_understanding.validation_ms,
        "llm_used": query_understanding.llm_used,
        "llm_fallback": query_understanding.llm_fallback,
    }
    if filter_adherence:
        embedding_meta["filter_adherence"] = filter_adherence
    if retrieval_debug_enabled() and retrieval_debug_ctx:
        embedding_meta["structured_query"] = structured_query.to_dict()
        embedding_meta["retrieval_trace"] = build_retrieval_trace(
            user_message=request.message,
            session_query=retrieval_debug_ctx["session_query"],
            turn_after_qu=retrieval_debug_ctx["turn_after_qu"],
            turn_after_validate=retrieval_debug_ctx["turn_after_validate"],
            merged=structured_query,
            plan=retrieval_plan,
            conversation_summary=retrieval_debug_ctx.get("conversation_summary"),
            vector_primary_source_type=vector_primary_source_type,
            enhanced_query=enhanced_query,
            retrieval_tier=retrieval_tier,
            match_mode=match_mode,
            dropped_filters=list(tiered.dropped_filters or []),
            hit_count=len(search_results),
            product_card_count=len(card_results),
        )
    _record_usage_event(
        db,
        tenant_id=session.tenant_id,
        usage_type=UsageType.chat_embedding,
        model_name=embedding_usage.get("model_name", ""),
        prompt_tokens=embedding_usage.get("prompt_tokens", 0),
        completion_tokens=embedding_usage.get("completion_tokens", 0),
        total_tokens=embedding_usage.get("total_tokens", 0),
        session_id=session.id,
        meta_json=embedding_meta,
    )
    context_texts: list[str] = []
    sources: list[SearchResult] = []
    result_context_payloads: list[dict[str, Any]] = []
    for result in response_results:
        original_url = result.payload["url"]
        validated_url = validate_and_fix_url(original_url, fallback_base=url_fallback) or get_base_url(original_url)
        if not validated_url:
            continue
        if not catalog_products_only:
            context_texts.append(
                f"Source: {result.payload['source']}\nURL: {validated_url}\n{result.payload['content']}"
            )
            sources.append(
                SearchResult(
                    content=result.payload["content"][:200] + "...",
                    source=result.payload["source"],
                    url=validated_url,
                    score=result.score,
                )
            )
        result_context_payloads.append(build_result_context_payload({**result.payload, "url": validated_url}))
    price_relaxed = tiered.price_relaxed
    if structured_query.intent == "catalog":
        products = _build_chat_products(card_results, match_scores or None)
    if structured_query.intent == "catalog":
        brand = _tenant_chat_brand_label(tenant_row)
        site = (tenant_row.widget_website_url or "").strip() if tenant_row else ""
        site_clause = (
            f" Official website (for grounding references only): {site}."
            if site
            else ""
        )
        price_min = retrieval_plan.price_min
        price_max = retrieval_plan.price_max
        catalog_prompt = build_catalog_grounded_system_prompt(
            brand,
            match_mode=match_mode,
            retrieval_tier=retrieval_tier,
            price_min=price_min,
            price_max=price_max,
            price_relaxed=price_relaxed,
            site_clause=site_clause,
            filter_adherence=filter_adherence,
            products_empty=not products,
        )
        answer, completion_usage = await generate_answer(
            request.message,
            context_texts,
            system_prompt=catalog_prompt,
            catalog_products_json=format_products_for_prompt(products) if products else "[]",
        )
        from retrieval.response_verifier import verify_catalog_response

        answer, _verified = await verify_catalog_response(
            user_message=request.message,
            answer=answer,
            products=[p.model_dump() if hasattr(p, "model_dump") else dict(p) for p in products],
            llm_call=openai_adapter.create_structured_completion,
        )
        if commerce_intro:
            answer = f"{commerce_intro}\n\n{answer}".strip()
        confidence = response_results[0].score if response_results else 0.0
    elif not sources:
        if structured_query.intent == "support":
            answer = (
                "I could not find return or policy information in the indexed content for this store. "
                "It may not be in the Magento CMS tables yet—add a CMS page or include a static policy URL "
                "in tenant source settings, then reindex."
            )
        else:
            answer = "I could not find high-confidence context for that request."
        confidence = 0.0
        completion_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "model_name": "gpt-3.5-turbo"}
    else:
        answer, completion_usage = await generate_answer(
            request.message,
            context_texts,
            system_prompt=_build_chat_system_prompt(
                tenant_row,
                intent=structured_query.intent,
                match_mode=match_mode,
            ),
        )
        confidence = response_results[0].score if response_results else 0.0
    source_type = "vector_search"
    write_sq = session_structured_query_for_writeback(
        structured_query=structured_query,
        session_state=session_state,
        classification=classification,
    )
    session_state = structured_query_to_session_state(
        structured_query=write_sq,
        user_message=request.message,
        result_context=result_context_payloads,
        recent_requests=list(session_state.get("recent_requests") or []),
        filter_stack=filter_stack,
    )

    answer, products, commerce_actions, response_subtype, commerce_meta = await _apply_turn_adequacy(
        message=request.message,
        answer=answer,
        response_subtype=response_subtype,
        classification=classification,
        products=products or None,
        actions=commerce_actions or None,
        website_url=website_url,
        structured_query_intent=structured_query.intent,
        meta=commerce_meta,
    )

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
            "retrieval_tier": retrieval_tier,
            "match_mode": match_mode,
            "query_understanding_mode": query_understanding.mode,
            "rules_prepass_ms": query_understanding.prepass_ms,
            "llm_ms": query_understanding.llm_ms,
            "validation_ms": query_understanding.validation_ms,
        },
    )
    db.add(assistant_message)
    db.flush()
    _set_chat_session_state(session, session_state)
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
    retrieval_debug_payload = None
    if retrieval_debug_enabled():
        retrieval_debug_payload = embedding_meta.get("retrieval_trace")
    return ChatResponse(
        response=answer,
        session_id=str(session.id),
        message_id=str(assistant_message.id),
        source=source_type,
        confidence=confidence,
        sources=sources or None,
        products=products or None,
        categories=[ChatCategoryLink(**c) for c in commerce_categories] if commerce_categories else None,
        actions=[ChatAction(**a) for a in commerce_actions] if commerce_actions else None,
        meta=commerce_meta or None,
        response_subtype=response_subtype,
        retrieval_tier=retrieval_tier,
        match_mode=match_mode,
        retrieval_debug=retrieval_debug_payload,
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
    if not _tenant_origin_allowed(tenant, _effective_widget_origin(request_obj, origin)):
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
        "source_type": resolve_vector_primary_source_type(
            widget_source_type=tenant.widget_source_type,
            source_db_type=tenant.source_db_type,
            source_mode=tenant.source_mode,
            source_db_url=tenant.source_db_url,
            source_static_urls_json=tenant.source_static_urls_json,
        ),
        "user_message_color": tenant.widget_user_message_color,
        "bot_message_color": tenant.widget_bot_message_color,
        "user_message_text_color": tenant.widget_user_message_text_color,
        "bot_message_text_color": tenant.widget_bot_message_text_color,
        "header_title": tenant.widget_header_title,
        "welcome_message": tenant.widget_welcome_message,
        "avatar_url": _normalize_avatar_url_for_widget(tenant.avatar_url),
        "privacy_policy_url": tenant.privacy_policy_url,
        "idle_rating_wait_seconds": tenant.idle_rating_wait_seconds,
        "max_results_default": effective_chat_max_results(tenant=tenant, request_max=None),
        "max_results_absolute_ceiling": max(1, int(os.getenv("CHAT_MAX_RESULTS_ABSOLUTE_CEILING", "50"))),
        "currency": _tenant_currency(tenant),
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
    if not _tenant_origin_allowed(tenant, _effective_widget_origin(request_obj, origin)):
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
    if not _tenant_origin_allowed(tenant, _effective_widget_origin(request_obj, origin)):
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
            "source_db_type": normalize_source_provider(
                t.source_db_type,
                source_mode=t.source_mode,
                source_db_url=t.source_db_url,
                source_static_urls_json=t.source_static_urls_json,
            ),
            "source_table_prefix": t.source_table_prefix,
            "source_url_table": t.source_url_table,
            "source_mode": t.source_mode,
            "source_static_urls_json": t.source_static_urls_json,
            "source_domain_aliases": t.source_domain_aliases,
            "source_canonical_base_url": t.source_canonical_base_url,
            "source_plan": plan_to_dict(resolve_source_plan(_provider_aware_source_config(t))),
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
            "chat_max_results": t.chat_max_results,
            "chat_max_results_catalog": t.chat_max_results_catalog,
            "retrieval_profile_version": t.retrieval_profile_version,
            "retrieval_profile_summary": retrieval_profile_summary(t.retrieval_profile_json),
        }
        for t in tenants
    ]


@app.get("/api/admin/tenants/{tenant_id}/retrieval-profile")
async def get_tenant_retrieval_profile(
    tenant_id: str,
    user_ctx=Depends(get_current_user),
    db=Depends(db_session),
):
    _ensure_manage_tenant(db, user_ctx, tenant_id)
    tenant = db.get(Tenant, uuid.UUID(tenant_id))
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if not tenant.retrieval_profile_json:
        return {
            "tenant_id": tenant_id,
            "retrieval_profile_version": tenant.retrieval_profile_version,
            "profile": None,
            "summary": None,
        }
    return {
        "tenant_id": tenant_id,
        "retrieval_profile_version": tenant.retrieval_profile_version,
        "profile": tenant.retrieval_profile_json,
        "summary": retrieval_profile_summary(tenant.retrieval_profile_json),
    }


@app.patch("/api/admin/tenants/{tenant_id}/retrieval-profile/gazetteer")
async def patch_tenant_retrieval_profile_gazetteer(
    tenant_id: str,
    payload: RetrievalProfileGazetteerPatchRequest,
    user_ctx=Depends(get_current_user),
    db=Depends(db_session),
):
    _ensure_manage_tenant(db, user_ctx, tenant_id)
    tenant = db.get(Tenant, uuid.UUID(tenant_id))
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    profile = tenant.retrieval_profile_json
    if not profile:
        raise HTTPException(status_code=400, detail="Tenant has no retrieval profile; run reindex first")
    gazetteer = list((profile.get("category_strategy") or {}).get("gazetteer") or [])
    by_id = {str(entry.get("id") or ""): entry for entry in gazetteer if entry.get("id")}
    updated_ids: list[str] = []
    for patch in payload.entries:
        entry_id = (patch.id or "").strip().lower()
        if not entry_id or entry_id not in by_id:
            raise HTTPException(status_code=400, detail=f"Unknown gazetteer id: {patch.id}")
        entry = by_id[entry_id]
        if patch.hard_filter is not None:
            if patch.hard_filter:
                entry["hard_filter"] = True
            else:
                entry.pop("hard_filter", None)
        if patch.demote_accessory_substrings is not None:
            if patch.demote_accessory_substrings:
                entry["demote_accessory_substrings"] = True
            else:
                entry.pop("demote_accessory_substrings", None)
        if patch.fixture_stem is not None:
            stem = patch.fixture_stem.strip()
            if stem:
                entry["fixture_stem"] = stem
            else:
                entry.pop("fixture_stem", None)
        if patch.accessory_keywords is not None:
            keywords = [str(k).strip().lower() for k in patch.accessory_keywords if str(k).strip()]
            if keywords:
                entry["accessory_keywords"] = keywords
            else:
                entry.pop("accessory_keywords", None)
        updated_ids.append(entry_id)
    strategy = dict(profile.get("category_strategy") or {})
    strategy["gazetteer"] = [by_id[str(entry.get("id") or "")] for entry in gazetteer]
    profile = dict(profile)
    profile["category_strategy"] = strategy
    tenant.retrieval_profile_json = profile
    db.add(tenant)
    db.commit()
    return {
        "tenant_id": tenant_id,
        "updated_ids": updated_ids,
        "retrieval_profile_version": tenant.retrieval_profile_version,
        "summary": retrieval_profile_summary(profile),
    }


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

    normalized_mode_input = (payload.source_mode or "").strip().lower() if payload.source_mode is not None else None
    if normalized_mode_input is not None and normalized_mode_input not in {"wordpress", "static", "mixed", "magento", ""}:
        raise HTTPException(status_code=400, detail="source_mode must be one of: wordpress, static, mixed, magento")

    effective_source_db_url = payload.source_db_url if payload.source_db_url is not None else tenant.source_db_url
    effective_source_db_type_raw = payload.source_db_type if payload.source_db_type is not None else tenant.source_db_type
    effective_source_mode_raw = (
        normalized_mode_input if payload.source_mode is not None else tenant.source_mode
    )

    source_static_raw = payload.source_static_urls_json if payload.source_static_urls_json is not None else tenant.source_static_urls_json

    source_provider = normalize_source_provider(
        effective_source_db_type_raw,
        source_mode=effective_source_mode_raw,
        source_db_url=effective_source_db_url,
        source_static_urls_json=source_static_raw,
    )
    effective_source_mode = coerce_source_mode_for_provider(source_provider, effective_source_mode_raw)
    source_mode = effective_source_mode
    if source_provider == "static":
        effective_source_mode = "static"
        source_mode = "static"
    if payload.source_db_type is not None:
        raw_provider = (payload.source_db_type or "").strip().lower()
        if raw_provider not in {"", "wordpress", "woocommerce", "magento", "static"}:
            raise HTTPException(status_code=400, detail="source_db_type must be one of: wordpress, woocommerce, magento, static")
        if raw_provider in {"woocommerce", "magento"} and not (effective_source_db_url or ""):
            raise HTTPException(status_code=400, detail=f"{raw_provider} provider requires source_db_url")
        if raw_provider == "static" and not (source_static_raw or ""):
            raise HTTPException(status_code=400, detail="static provider requires source_static_urls_json")

    canonical_base = (tenant.source_canonical_base_url or "").strip() or None
    if payload.source_canonical_base_url is not None:
        canonical_base = (payload.source_canonical_base_url or "").strip() or None
    if canonical_base and not _is_http_url(canonical_base):
        raise HTTPException(status_code=400, detail="source_canonical_base_url must be a valid http(s) URL")

    domain_aliases_csv = tenant.source_domain_aliases
    alias_values: List[str] = []
    existing_aliases = (tenant.source_domain_aliases or "").strip()
    if existing_aliases:
        alias_values = [a.strip() for a in existing_aliases.split(",") if a.strip()]
    if payload.source_domain_aliases is not None:
        raw_aliases = payload.source_domain_aliases.strip()
        if raw_aliases:
            alias_values = [a.strip() for a in re.split(r"[,\n]+", raw_aliases) if a.strip()]
        else:
            alias_values = []
        invalid_aliases = [a for a in alias_values if not _is_http_url(a)]
        if invalid_aliases:
            raise HTTPException(status_code=400, detail="source_domain_aliases must be comma/newline separated http(s) URLs")
        domain_aliases_csv = ",".join(alias_values) if alias_values else None

    source_static_urls_json = _normalize_source_static_urls_json(
        source_static_raw,
        domain_aliases=alias_values,
        canonical_base=canonical_base,
    )

    tenant.source_db_url = effective_source_db_url
    tenant.source_db_type = source_provider
    if payload.source_table_prefix is not None:
        tenant.source_table_prefix = (payload.source_table_prefix or "").strip() or None
    if payload.source_url_table is not None:
        tenant.source_url_table = (payload.source_url_table or "").strip() or None
    tenant.source_mode = effective_source_mode
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
                "source_db_type": source_provider,
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

    branding_updates = payload.model_dump(exclude_unset=True)
    if "chat_max_results" in branding_updates:
        tenant.chat_max_results = branding_updates["chat_max_results"]
    if "chat_max_results_catalog" in branding_updates:
        tenant.chat_max_results_catalog = branding_updates["chat_max_results_catalog"]

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
    running_jobs = db.execute(
        select(ReindexJob).where(ReindexJob.status == "running").order_by(ReindexJob.created_at.desc())
    ).scalars().all()
    existing_job = next((job for job in running_jobs if _reindex_job_targets_tenant(job, target_tenant_id)), None)
    if existing_job:
        return {
            "job_id": str(existing_job.id),
            "status": "already_running",
            "message": "A reindex job is already running for this tenant.",
        }
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

            planned_total_records: int | None = None
            last_progress_commit_at = 0.0
            progress_commit_interval_s = max(
                1.0,
                float(os.getenv("REINDEX_PROGRESS_COMMIT_INTERVAL_SECONDS", "2")),
            )

            def on_progress(progress: Dict[str, Any]):
                nonlocal planned_total_records, last_progress_commit_at
                if planned_total_records is None and progress.get("planned_total_records"):
                    planned_total_records = int(progress["planned_total_records"])
                normalized = normalize_reindex_progress(
                    progress,
                    planned_total_records=planned_total_records,
                    job_status="running",
                )
                local_job.meta_json = {
                    "target_tenant_id": target_tenant_id,
                    "progress": normalized,
                }
                local_db.add(local_job)
                now = time.time()
                if now - last_progress_commit_at >= progress_commit_interval_s:
                    local_db.commit()
                    last_progress_commit_at = now

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
                source_cfg = _provider_aware_source_config(tenant)
            payload_st = LEGACY_VECTOR_PRIMARY_SOURCE_TYPE
            payload_label = LEGACY_VECTOR_PRIMARY_SOURCE_LABEL
            url_fb = None
            if tenant:
                payload_st = resolve_vector_primary_source_type(
                    widget_source_type=tenant.widget_source_type,
                    source_db_type=tenant.source_db_type,
                    source_mode=tenant.source_mode,
                    source_db_url=tenant.source_db_url,
                    source_static_urls_json=tenant.source_static_urls_json,
                )
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
            reindex_result = await embedder.reindex_all_content(
                source_job_id=str(job_id),
                previous_profile_version=tenant.retrieval_profile_version if tenant else None,
            )
            local_db.commit()
            profile = reindex_result.get("retrieval_profile")
            if tenant and profile:
                apply_retrieval_profile_to_tenant(tenant, profile)
                local_db.add(tenant)
            local_job.status = "completed"
            local_job.finished_at = datetime.now(timezone.utc)
            final_progress = normalize_reindex_progress(
                embedder.get_indexing_status().get("progress", {}),
                planned_total_records=planned_total_records,
                job_status="completed",
            )
            local_job.meta_json = {
                "target_tenant_id": target_tenant_id,
                "progress": final_progress,
                "retrieval_profile_version": profile.get("profile_version") if profile else None,
                "retrieval_profile_facet_count": len((profile or {}).get("facets") or {}),
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
    items = []
    for j in jobs:
        meta = dict(j.meta_json or {})
        raw_progress = (meta.get("progress") or {}) if isinstance(meta.get("progress"), dict) else {}
        meta["progress"] = normalize_reindex_progress(
            raw_progress,
            planned_total_records=int(raw_progress.get("planned_total_records") or raw_progress.get("total_items") or 0) or None,
            job_status=j.status,
        )
        items.append(
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
                "meta": meta,
            }
        )
    return items

# Run the app
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app:app",
        host=os.getenv("API_HOST", "0.0.0.0"), 
        port=int(os.getenv("API_PORT", 8043)),
        reload=False,
    ) 