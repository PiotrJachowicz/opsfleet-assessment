import uuid

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    user_id: str = Field(min_length=1)
    conversation_id: uuid.UUID | None = None
    message: str = Field(min_length=1)
