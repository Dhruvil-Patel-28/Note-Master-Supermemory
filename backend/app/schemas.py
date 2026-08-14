from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict


CaptureType = Literal["text", "voice", "doc"]
CaptureStatus = Literal["queued", "processing", "indexed", "failed"]
SensitivityTier = Literal["none", "moderate", "high"]


class TextCaptureIn(BaseModel):
    content: str


class CaptureOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: CaptureType
    content: str
    raw_content_ref: Optional[str] = None
    status: CaptureStatus
    error: Optional[str] = None
    sensitivity_tier: SensitivityTier
    document_group_id: Optional[int] = None
    version_number: int
    is_latest: bool
    created_at: str
    updated_at: str


class CaptureUpdateIn(BaseModel):
    content: str


class FtsHit(BaseModel):
    capture_id: int
    snippet: str
    score: float


class ChatRequest(BaseModel):
    query: str
    include_history: bool = False


class ChatSource(BaseModel):
    capture_id: int
    snippet: str
    sensitivity_tier: str = "none"


class StructuredField(BaseModel):
    key: str
    value: str


class StructuredAnswer(BaseModel):
    kind: Literal["fields", "prose"]
    fields: list[StructuredField] = []


class ChatResponse(BaseModel):
    answer: str
    found: bool
    sources: list[ChatSource]
    structured: Optional[StructuredAnswer] = None
    needs_pin: bool = False