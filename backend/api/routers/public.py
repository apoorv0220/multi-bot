from typing import Optional

from fastapi import APIRouter, Depends, Header, Request

import main as legacy_main
from services import chat_service, public_service


router = APIRouter(tags=["public"])


@router.post("/api/public/chat", response_model=legacy_main.ChatResponse)
async def public_chat(
    request: legacy_main.ChatRequest,
    request_obj: Request,
    db=Depends(legacy_main.db_session),
    x_widget_key: Optional[str] = Header(default=None, alias="X-Widget-Key"),
    x_visitor_id: Optional[str] = Header(default=None, alias="X-Visitor-Id"),
    origin: Optional[str] = Header(default=None),
):
    return await chat_service.run_public_chat(
        request=request,
        db=db,
        x_widget_key=x_widget_key,
        x_visitor_id=x_visitor_id,
        origin=origin,
        request_obj=request_obj,
    )


@router.get("/api/public/visitor-profile")
async def get_public_visitor_profile(
    request_obj: Request,
    db=Depends(legacy_main.db_session),
    x_widget_key: Optional[str] = Header(default=None, alias="X-Widget-Key"),
    x_visitor_id: Optional[str] = Header(default=None, alias="X-Visitor-Id"),
    origin: Optional[str] = Header(default=None),
):
    return await public_service.get_visitor_profile(
        db=db,
        x_widget_key=x_widget_key,
        x_visitor_id=x_visitor_id,
        origin=origin,
        request_obj=request_obj,
    )


@router.get("/api/public/config")
async def get_public_config(
    db=Depends(legacy_main.db_session),
    x_widget_key: Optional[str] = Header(default=None, alias="X-Widget-Key"),
    origin: Optional[str] = Header(default=None),
):
    return await public_service.get_widget_config(db=db, x_widget_key=x_widget_key, origin=origin)


@router.post("/api/public/visitor-profile")
async def upsert_public_visitor_profile(
    payload: legacy_main.PublicVisitorProfileRequest,
    request_obj: Request,
    db=Depends(legacy_main.db_session),
    x_widget_key: Optional[str] = Header(default=None, alias="X-Widget-Key"),
    origin: Optional[str] = Header(default=None),
):
    return await public_service.upsert_visitor_profile(
        payload=payload,
        db=db,
        x_widget_key=x_widget_key,
        origin=origin,
        request_obj=request_obj,
    )


@router.post("/api/public/messages/{message_id}/feedback")
async def add_public_feedback(
    message_id: str,
    payload: legacy_main.FeedbackRequest,
    request_obj: Request,
    db=Depends(legacy_main.db_session),
    x_widget_key: Optional[str] = Header(default=None, alias="X-Widget-Key"),
    origin: Optional[str] = Header(default=None),
):
    return await public_service.add_public_feedback(
        message_id=message_id,
        payload=payload,
        db=db,
        x_widget_key=x_widget_key,
        origin=origin,
        request_obj=request_obj,
    )


@router.get("/api/assets/{filename}")
async def get_uploaded_asset(filename: str):
    return await legacy_main.get_uploaded_asset(filename=filename)
