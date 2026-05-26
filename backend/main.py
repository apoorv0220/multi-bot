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

from integrations.chat_retrieval import (
    ensure_collection_for_tenant,
    generate_embedding,
    init_qdrant_client,
    qdrant_client,
    search_qdrant,
    tenant_collection as _tenant_collection,
)
from services.commerce_chat_service import (
    run_chat_for_tenant as _run_chat_for_tenant,
    _get_chat_session_state,
    _set_chat_session_state,
    _record_usage_event,
)

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
    init_qdrant_client()
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



# HTTP handlers in api/legacy_handlers.py (R7/R8)
from api.legacy_handlers import *  # noqa: F403
from api.legacy_handlers import (
    _canonicalize_source_url,
    _normalize_source_static_urls_json,
    _provider_aware_source_config,
    _slugify,
)
from services.commerce_chat_service import _tenant_chat_brand_label

# Run the app
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app:app",
        host=os.getenv("API_HOST", "0.0.0.0"), 
        port=int(os.getenv("API_PORT", 8043)),
        reload=False,
    ) 
