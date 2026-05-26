from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class SearchResult(BaseModel):
    content: str
    source: str
    url: str
    score: float


class ChatProduct(BaseModel):
    title: str
    url: str
    price: Optional[float] = None
    brand: Optional[str] = None
    image_url: Optional[str] = None
    score: Optional[float] = None
    rating: Optional[float] = None
    review_count: Optional[int] = None
    match_quality: Optional[str] = None
    missed_constraints: Optional[List[str]] = None
    currency: Optional[str] = None


class ChatCategoryLink(BaseModel):
    name: str
    url: Optional[str] = None
    product_count: Optional[int] = None


class ChatAction(BaseModel):
    type: str = "link"
    label: str
    url: str


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    max_results: Optional[int] = Field(default=None, ge=1, le=100)


class ChatResponse(BaseModel):
    response: str
    session_id: str
    message_id: str
    source: Optional[str] = None
    confidence: Optional[float] = None
    sources: Optional[List[SearchResult]] = None
    products: Optional[List[ChatProduct]] = None
    categories: Optional[List[ChatCategoryLink]] = None
    actions: Optional[List[ChatAction]] = None
    meta: Optional[Dict[str, Any]] = None
    response_subtype: Optional[str] = None
    retrieval_tier: Optional[str] = None
    match_mode: Optional[str] = None
    retrieval_debug: Optional[Dict[str, Any]] = None
