"""Commerce chat pipeline extracted from main.py (R5)."""
import logging
import os
import re
import time
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import openai
from fastapi import HTTPException
from sqlalchemy import select

from api.schemas.chat import ChatAction, ChatCategoryLink, ChatProduct, ChatRequest, ChatResponse, SearchResult
from commerce.currency import currency_from_profile, normalize_currency_code
from fuzzy_matcher import get_tenant_quick_reply
from indexing.payloads import build_result_context_payload
from integrations.chat_retrieval import (
    ensure_collection_for_tenant,
    generate_embedding,
    get_qdrant_client,
    openai_adapter,
    search_qdrant,
)
from models import (
    AuditLog,
    BlockWordMatchMode,
    ChatMessage,
    ChatSession,
    ChatVisitor,
    SenderType,
    Tenant,
    TenantBlockWord,
    TenantBlockWordCategory,
    UsageEvent,
    UsageType,
)
from retrieval.catalog_cards import filter_results_for_catalog_cards, filter_results_for_response_sources
from retrieval.catalog_response import build_catalog_grounded_system_prompt, format_products_for_prompt
from retrieval.chat_orchestrator import (
    apply_sort_to_results,
    build_static_response,
    classify_turn,
    ensure_commerce_catalog_intent,
    session_structured_query_for_writeback,
)
from retrieval.filter_adherence import build_filter_adherence
from retrieval.match_quality import classify_match_quality_for_results, finalize_response_subtype
from retrieval.max_results import effective_chat_max_results, parse_explicit_result_cap
from retrieval.planner import RetrievalPlan, apply_retrieval_rewrite, build_retrieval_plan
from retrieval.post_filter import apply_score_threshold, catalog_match_mode_instruction, effective_score_threshold
from retrieval.price_validation import has_invalid_price
from retrieval.query_understanding import QueryUnderstandingResult, run_query_understanding
from retrieval.query_validator import validate_structured_query
from retrieval.response_composer import compose_search_intro
from retrieval.session_query import (
    SESSION_RESET_MESSAGE,
    classify_merge_action,
    empty_structured_query,
    is_session_reset_turn,
    load_structured_query_from_session,
    merge_session_query,
    structured_query_to_session_state,
    update_filter_stack,
)
from retrieval.structured_query import StructuredQuery
from retrieval.tiered_search import execute_tiered_search
from retrieval.tools.product_refs import extract_product_title_from_message
from retrieval.trace import build_retrieval_trace, retrieval_debug_enabled
from sources.config import resolve_vector_primary_source_type
from url_utils import get_base_url, validate_and_fix_url

logger = logging.getLogger("chatbot-api")

_SINGULAR_CHEAPEST_RE = re.compile(
    r"\b(?:what(?:'|\s+is)\s+the\s+cheapest|the\s+cheapest\s+(?:product|item))\b",
    re.IGNORECASE,
)

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


async def run_chat_for_tenant(
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
    if get_qdrant_client() is None:
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
