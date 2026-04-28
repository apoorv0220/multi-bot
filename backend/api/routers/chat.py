from fastapi import APIRouter, Depends

import main as legacy_main
from services import chat_service


router = APIRouter(tags=["chat"])


@router.post("/api/chat", response_model=legacy_main.ChatResponse)
async def chat(
    request: legacy_main.ChatRequest,
    user_ctx=Depends(legacy_main.get_current_user),
    db=Depends(legacy_main.db_session),
):
    return await chat_service.run_authenticated_chat(request=request, user_ctx=user_ctx, db=db)


@router.post("/api/messages/{message_id}/feedback")
async def add_feedback(
    message_id: str,
    payload: legacy_main.FeedbackRequest,
    user_ctx=Depends(legacy_main.get_current_user),
    db=Depends(legacy_main.db_session),
):
    return await legacy_main.add_feedback(message_id=message_id, payload=payload, user_ctx=user_ctx, db=db)
