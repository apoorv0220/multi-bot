from typing import Optional

from pydantic import BaseModel, EmailStr

from models import FeedbackVote


class PublicVisitorProfileRequest(BaseModel):
    visitor_id: str
    name: str
    email: EmailStr


class FeedbackRequest(BaseModel):
    vote: FeedbackVote
    reason: Optional[str] = ""


class PublicSessionRatingRequest(BaseModel):
    session_id: str
    rating: int
