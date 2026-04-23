import asyncio
import json
import logging
import os
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import unquote, urlparse

import openai
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr
from qdrant_client import QdrantClient
from qdrant_client.http import models
from qdrant_client.http.models import Distance, VectorParams
from sqlalchemy import select

from auth import create_access_token, decode_token, hash_password, verify_password
from db import SessionLocal
from embedder import Embedder
from fuzzy_matcher import FuzzyMatcher
from models import (
    AuditLog,
    ChatMessage,
    ChatSession,
    FeedbackVote,
    MessageFeedback,
    ReindexJob,
    ReindexScope,
    SenderType,
    Tenant,
    User,
    UserRole,
    UserTenant,
)
from url_utils import validate_and_fix_url, get_base_url

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
fuzzy_matcher = FuzzyMatcher()


@app.on_event("startup")
async def startup_event():
    global qdrant_client
    try:
        qdrant_client = _initialize_qdrant_client_with_retries()
    except Exception:
        qdrant_client = None


class AuthRequest(BaseModel):
    email: EmailStr
    password: str


class AuthResponse(BaseModel):
    access_token: str
    role: str
    tenant_id: Optional[str] = None


class SearchResult(BaseModel):
    content: str
    source: str
    url: str
    score: float


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    max_results: int = 5


class ChatResponse(BaseModel):
    response: str
    session_id: str
    message_id: str
    source: Optional[str] = None
    confidence: Optional[float] = None
    sources: Optional[List[SearchResult]] = None


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


class UserStatusRequest(BaseModel):
    is_active: bool


class ResetPasswordRequest(BaseModel):
    new_password: str


class TenantSourceConfigRequest(BaseModel):
    source_db_url: Optional[str] = None
    source_db_type: Optional[str] = None
    source_table_prefix: Optional[str] = None
    source_url_table: Optional[str] = None


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
    if user_ctx["role"] not in roles:
        raise HTTPException(status_code=403, detail="Insufficient permissions")


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


def _resolve_embed_tenant_id(embed_key: Optional[str]) -> str:
    if not embed_key:
        raise HTTPException(status_code=401, detail="Missing widget key")
    key_map = _load_widget_embed_key_map()
    tenant_id = key_map.get(embed_key)
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Invalid widget key")
    return tenant_id


def _resolve_tenant_actor_user_id(db, tenant_id: str) -> uuid.UUID:
    member = db.execute(
        select(UserTenant).where(UserTenant.tenant_id == uuid.UUID(tenant_id)).order_by(UserTenant.created_at.asc())
    ).scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=400, detail="No tenant user available for widget chat")
    user = db.get(User, member.user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=400, detail="No active tenant user available for widget chat")
    return user.id


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
async def generate_embedding(text: str) -> List[float]:
    try:
        response = openai.embeddings.create(
            model="text-embedding-3-small",
            input=text
        )
        return response.data[0].embedding
    except Exception as e:
        logger.error(f"Error generating embedding: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate embedding")

async def search_qdrant(tenant_id: str, embedding: List[float], limit: int = 5) -> List[Any]:
    if qdrant_client is None:
        raise HTTPException(status_code=503, detail="Qdrant service is unavailable")
    collection_name = _tenant_collection(tenant_id)

    try:
        # First try to search in MRN Web Designs content (prioritized)
        mrnwebdesigns_results = qdrant_client.search(
            collection_name=collection_name,
            query_vector=embedding,
            limit=limit,
            score_threshold=0.6,
            query_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="source_type",
                        match=models.MatchValue(value="mrnwebdesigns_ie")
                    )
                ]
            )
        )
        
        logger.info(f"Found {len(mrnwebdesigns_results)} mrnwebdesigns.com results")
        
        # If we don't have enough results from MRN Web Designs, search external sources
        if len(mrnwebdesigns_results) < limit or max([r.score for r in mrnwebdesigns_results] + [0]) < 0.7:
            external_results = qdrant_client.search(
                collection_name=collection_name,
                query_vector=embedding,
                query_filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="source_type",
                            match=models.MatchValue(value="external")
                        )
                    ]
                ),
                limit=limit
            )
            
            # Combine and sort results
            all_results = mrnwebdesigns_results + external_results
            all_results.sort(key=lambda x: x.score, reverse=True)
            logger.info(f"Added {len(external_results)} external results, total: {len(all_results)}")
            return all_results[:limit]
        
        return mrnwebdesigns_results
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

async def preprocess_query(original_query: str) -> str:
    """
    Use OpenAI to normalize and enhance queries for better search results.
    Converts questions like "your office address" to "MRN Web Designs office address".
    """
    try:
        response = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {
                    "role": "system", 
                    "content": """You are a query preprocessor for MRN Web Designs chatbot. Your job is to normalize and enhance user queries to make them more searchable in a knowledge base.

Rules:
1. Replace pronouns like "your", "you", "yours" with "MRN Web Designs"
2. Add relevant keywords that would help find information
3. Expand abbreviations and make queries more specific
4. Keep the original intent and meaning
5. Output only the enhanced query, nothing else

Examples:
- "your office address" → "MRN Web Designs office address location contact information"
- "what services do you offer" → "MRN Web Designs services web design development SEO digital marketing"
- "your pricing" → "MRN Web Designs pricing cost website development packages"
- "do you work with small businesses" → "MRN Web Designs small business services web design"
- "your experience" → "MRN Web Designs experience portfolio company background"
- "how can you help me" → "MRN Web Designs services help assistance web design digital marketing"
- "your phone number" → "MRN Web Designs phone number contact telephone call"
- "what is your contact number" → "MRN Web Designs contact phone number telephone"
- "how to reach you" → "MRN Web Designs contact phone address reach"
"""
                },
                {
                    "role": "user", 
                    "content": f"Original query: {original_query}"
                }
            ],
            max_tokens=100,
            temperature=0.1  # Low temperature for consistent results
        )
        
        enhanced_query = response.choices[0].message.content.strip()
        logger.info(f"Query enhanced: '{original_query}' → '{enhanced_query}'")
        return enhanced_query
        
    except Exception as e:
        logger.warning(f"Query preprocessing failed: {e}. Using original query.")
        return original_query

async def generate_answer(query: str, context_texts: List[str]) -> str:
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
        
        response = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a helpful assistant specialized in web design and digital marketing. Your role is to format information found in the context to provide accurate, helpful, and professional information about website design, development, maintenance, SEO, paid search, and social media marketing. Present this information as if it's directly from MRN Web Designs, a custom web design and digital marketing agency. Focus on helping businesses stand out from the competition by creating digital experiences that boost visibility and drive engagement. Always emphasize custom solutions over templates or cookie-cutter approaches. IMPORTANT: Keep your responses concise and under 250 characters to ensure clarity and readability."},
                {"role": "user", "content": f"Question: {query}\n\nContext: {context}"}
            ]
        )
        
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Error generating answer: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate answer")


async def _run_chat_for_tenant(
    request: ChatRequest,
    tenant_id: str,
    actor_user_id: uuid.UUID,
    db,
    is_public_chat: bool = False,
) -> Dict[str, Any]:
    ensure_collection_for_tenant(tenant_id)

    if request.session_id:
        session = db.get(ChatSession, uuid.UUID(request.session_id))
        if not session or str(session.tenant_id) != tenant_id:
            raise HTTPException(status_code=404, detail="Session not found")
    else:
        session = ChatSession(tenant_id=uuid.UUID(tenant_id), created_by_user_id=actor_user_id)
        db.add(session)
        db.flush()
        if is_public_chat:
            session.title = f"Anonymous {session.id}"

    db.add(
        ChatMessage(
            session_id=session.id,
            tenant_id=session.tenant_id,
            sender_type=SenderType.user,
            content=request.message,
            model_name="",
        )
    )

    fuzzy_response = fuzzy_matcher.get_response(request.message)
    if fuzzy_response:
        answer = fuzzy_response["response"]
        sources = fuzzy_response.get("sources", [])
        confidence = fuzzy_response.get("confidence", 1.0)
        source_type = "fuzzy"
    else:
        if qdrant_client is None:
            raise HTTPException(status_code=503, detail="Qdrant unavailable")
        enhanced_query = await preprocess_query(request.message)
        embedding = await generate_embedding(enhanced_query)
        search_results = await search_qdrant(tenant_id, embedding, request.max_results)
        filtered_results = [result for result in search_results if result.score >= 0.3]
        context_texts: list[str] = []
        sources: list[SearchResult] = []
        for result in filtered_results:
            original_url = result.payload["url"]
            validated_url = validate_and_fix_url(original_url) or get_base_url(original_url)
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
        else:
            answer = await generate_answer(request.message, context_texts)
            confidence = filtered_results[0].score
        source_type = "vector_search"

    assistant_message = ChatMessage(
        session_id=session.id,
        tenant_id=session.tenant_id,
        sender_type=SenderType.assistant,
        content=answer,
        model_name="gpt-3.5-turbo",
    )
    db.add(assistant_message)
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
    db.commit()
    ensure_collection_for_tenant(str(tenant.id))
    token = create_access_token(str(user.id), user.role.value, str(tenant.id))
    return AuthResponse(access_token=token, role=user.role.value, tenant_id=str(tenant.id))


@app.post("/api/auth/login", response_model=AuthResponse)
async def login(payload: AuthRequest, db=Depends(db_session)):
    user = db.execute(select(User).where(User.email == payload.email)).scalar_one_or_none()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    tenant_link = db.execute(select(UserTenant).where(UserTenant.user_id == user.id)).scalar_one_or_none()
    tenant_id = str(tenant_link.tenant_id) if tenant_link else None
    token = create_access_token(str(user.id), user.role.value, tenant_id)
    return AuthResponse(access_token=token, role=user.role.value, tenant_id=tenant_id)


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, user_ctx=Depends(get_current_user), db=Depends(db_session)) -> Dict[str, Any]:
    tenant_id = user_ctx["tenant_id"]
    if not tenant_id:
        raise HTTPException(status_code=400, detail="Tenant context missing")
    return await _run_chat_for_tenant(request, tenant_id, user_ctx["user"].id, db)


@app.post("/api/public/chat", response_model=ChatResponse)
async def public_chat(
    request: ChatRequest,
    db=Depends(db_session),
    x_widget_key: Optional[str] = Header(default=None, alias="X-Widget-Key"),
    origin: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    if os.getenv("WIDGET_REQUIRE_ORIGIN", "false").lower() == "true" and not _origin_allowed(origin):
        raise HTTPException(status_code=403, detail="Origin not allowed for widget")
    tenant_id = _resolve_embed_tenant_id(x_widget_key)
    actor_user_id = _resolve_tenant_actor_user_id(db, tenant_id)
    return await _run_chat_for_tenant(request, tenant_id, actor_user_id, db, is_public_chat=True)

@app.get("/health")
async def health_check():
    return {"status": "healthy", "qdrant": "connected" if qdrant_client else "unavailable"}


@app.post("/api/messages/{message_id}/feedback")
async def add_feedback(message_id: str, payload: FeedbackRequest, user_ctx=Depends(get_current_user), db=Depends(db_session)):
    message = db.get(ChatMessage, uuid.UUID(message_id))
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")
    if str(message.tenant_id) != user_ctx["tenant_id"] and user_ctx["role"] != UserRole.superadmin.value:
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


@app.get("/api/admin/chats")
async def admin_chats(
    user_ctx=Depends(get_current_user),
    db=Depends(db_session),
    q: Optional[str] = Query(default=None),
    tenant_id: Optional[str] = Query(default=None),
):
    role = user_ctx["role"]
    if role == UserRole.superadmin.value:
        stmt = select(ChatSession)
        if tenant_id:
            stmt = stmt.where(ChatSession.tenant_id == uuid.UUID(tenant_id))
        sessions = db.execute(stmt.order_by(ChatSession.last_message_at.desc())).scalars().all()
    else:
        sessions = db.execute(
            select(ChatSession)
            .where(ChatSession.tenant_id == uuid.UUID(user_ctx["tenant_id"]))
            .order_by(ChatSession.last_message_at.desc())
        ).scalars().all()
    if q:
        q_l = q.lower()
        sessions = [s for s in sessions if q_l in (s.title or "").lower() or q_l in str(s.id)]
    return [{"id": str(s.id), "tenant_id": str(s.tenant_id), "title": s.title, "last_message_at": s.last_message_at.isoformat()} for s in sessions]


@app.get("/api/admin/users")
async def admin_users(
    user_ctx=Depends(get_current_user),
    db=Depends(db_session),
    tenant_id: Optional[str] = Query(default=None),
):
    if user_ctx["role"] == UserRole.superadmin.value:
        if tenant_id:
            tenant_uuid = uuid.UUID(tenant_id)
            user_ids = db.execute(select(UserTenant.user_id).where(UserTenant.tenant_id == tenant_uuid)).scalars().all()
            users = db.execute(
                select(User)
                .where(User.id.in_(list(user_ids)))
                .where(User.role != UserRole.superadmin)
                .order_by(User.created_at.desc())
            ).scalars().all()
        else:
            users = db.execute(select(User).order_by(User.created_at.desc())).scalars().all()
    else:
        tenant_uuid = uuid.UUID(user_ctx["tenant_id"])
        user_ids = db.execute(select(UserTenant.user_id).where(UserTenant.tenant_id == tenant_uuid)).scalars().all()
        users = db.execute(
            select(User)
            .where(User.id.in_(list(user_ids)))
            .where(User.role != UserRole.superadmin)
            .order_by(User.created_at.desc())
        ).scalars().all()
    return [
        {
            "id": str(u.id),
            "email": u.email,
            "role": u.role.value,
            "is_active": u.is_active,
            "created_at": u.created_at.isoformat(),
        }
        for u in users
    ]


@app.get("/api/admin/tenants")
async def admin_tenants(user_ctx=Depends(get_current_user), db=Depends(db_session)):
    if user_ctx["role"] == UserRole.superadmin.value:
        tenants = db.execute(select(Tenant).order_by(Tenant.created_at.desc())).scalars().all()
    else:
        tenant = db.get(Tenant, uuid.UUID(user_ctx["tenant_id"]))
        tenants = [tenant] if tenant else []
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
            "has_source_db_url": bool(t.source_db_url),
        }
        for t in tenants
    ]


@app.patch("/api/admin/tenants/{tenant_id}/source-config")
async def update_tenant_source_config(tenant_id: str, payload: TenantSourceConfigRequest, user_ctx=Depends(get_current_user), db=Depends(db_session)):
    tenant = db.get(Tenant, uuid.UUID(tenant_id))
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if user_ctx["role"] != UserRole.superadmin.value and str(tenant.id) != user_ctx["tenant_id"]:
        raise HTTPException(status_code=403, detail="Forbidden")

    tenant.source_db_url = payload.source_db_url
    tenant.source_db_type = payload.source_db_type
    tenant.source_table_prefix = payload.source_table_prefix
    tenant.source_url_table = payload.source_url_table
    tenant.updated_at = datetime.now(timezone.utc)
    db.add(
        AuditLog(
            actor_user_id=user_ctx["user"].id,
            actor_role=user_ctx["role"],
            tenant_id=tenant.id,
            action="tenant_source_config_updated",
            target_type="tenant",
            target_id=str(tenant.id),
            details_json={"source_db_type": payload.source_db_type},
        )
    )
    db.commit()
    return {"status": "ok", "tenant_id": str(tenant.id)}


@app.post("/api/admin/users")
async def create_admin_user(payload: AdminCreateRequest, user_ctx=Depends(get_current_user), db=Depends(db_session)):
    require_role(user_ctx, [UserRole.superadmin.value])
    existing = db.execute(select(User).where(User.email == payload.email)).scalar_one_or_none()
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
        role=UserRole.admin,
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
            action="admin_created",
            target_type="user",
            target_id=str(user.id),
            details_json={"email": payload.email},
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

    if user_ctx["role"] != UserRole.superadmin.value:
        tenant_uuid = uuid.UUID(user_ctx["tenant_id"])
        membership = db.execute(
            select(UserTenant).where(UserTenant.user_id == target_user.id, UserTenant.tenant_id == tenant_uuid)
        ).scalar_one_or_none()
        if not membership:
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
    if user_ctx["role"] != UserRole.superadmin.value:
        tenant_uuid = uuid.UUID(user_ctx["tenant_id"])
        membership = db.execute(
            select(UserTenant).where(UserTenant.user_id == target_user.id, UserTenant.tenant_id == tenant_uuid)
        ).scalar_one_or_none()
        if not membership:
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
    if user_ctx["role"] != UserRole.superadmin.value and str(session.tenant_id) != user_ctx["tenant_id"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    messages = db.execute(
        select(ChatMessage).where(ChatMessage.session_id == session.id).order_by(ChatMessage.created_at.asc())
    ).scalars().all()
    return [{"id": str(m.id), "sender_type": m.sender_type.value, "content": m.content, "created_at": m.created_at.isoformat()} for m in messages]


@app.post("/api/reindex")
async def trigger_reindex(request: ReindexRequest, user_ctx=Depends(get_current_user), db=Depends(db_session)):
    target_tenant_id = request.tenant_id or user_ctx["tenant_id"]
    if not target_tenant_id:
        raise HTTPException(status_code=400, detail="Tenant ID required")
    if user_ctx["role"] != UserRole.superadmin.value and target_tenant_id != user_ctx["tenant_id"]:
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

            source_cfg = {}
            if tenant:
                source_cfg = _parse_source_dsn(
                    tenant.source_db_url,
                    tenant.source_table_prefix,
                    tenant.source_url_table,
                )
            embedder = Embedder(
                client=qdrant_client,
                collection_name=_tenant_collection(target_tenant_id),
                source_config=source_cfg,
                progress_callback=on_progress,
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
        jobs = db.execute(
            select(ReindexJob).where(ReindexJob.tenant_id == uuid.UUID(user_ctx["tenant_id"])).order_by(ReindexJob.created_at.desc())
        ).scalars().all()
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
            content={"detail": f"Internal server error: {str(e)}"}
        )

# Run the app
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app", 
        host=os.getenv("API_HOST", "0.0.0.0"), 
        port=int(os.getenv("API_PORT", 8043)),
        reload=False,
    ) 