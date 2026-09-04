from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


PersonaDocumentName = Literal["SOUL", "MEMORY", "STYLE"]


class ProfileWrite(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)
    birth_date: str | None = None
    location: str = Field(default="", max_length=160)
    occupation: str = Field(default="", max_length=160)
    bio: str = Field(default="", max_length=2_000)
    goals: str = Field(default="", max_length=2_000)


class ProfileRecord(ProfileWrite):
    updated_at: datetime = Field(default_factory=utc_now)


class ThoughtCellReview(BaseModel):
    status: Literal["confirmed", "rejected", "unreviewed"]


class OralHistoryAnswerWrite(BaseModel):
    answer: str = Field(min_length=1, max_length=20_000)


class PersonCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)
    birth_date: str | None = None
    timezone: str = "Asia/Shanghai"


class PersonRecord(PersonCreate):
    id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=utc_now)


class PersonaDocumentWrite(BaseModel):
    content: str = Field(min_length=1, max_length=500_000)
    evidence_ids: list[str] = Field(default_factory=list)
    change_note: str = Field(default="manual update", max_length=500)


class PersonaDocumentRecord(PersonaDocumentWrite):
    document: PersonaDocumentName
    version: int
    updated_at: datetime = Field(default_factory=utc_now)


class VoiceConsentCreate(BaseModel):
    purpose: str = Field(min_length=3, max_length=240)
    expires_at: datetime | None = None
    confirmed_right_to_voice: bool
    allow_storage: bool = False


class VoiceConsentRecord(VoiceConsentCreate):
    id: UUID = Field(default_factory=uuid4)
    person_id: UUID
    scope: Literal["voice_clone"] = "voice_clone"
    status: Literal["active", "revoked"] = "active"
    granted_at: datetime = Field(default_factory=utc_now)

    def is_usable_for(self, requested_purpose: str) -> bool:
        if self.status != "active" or not self.confirmed_right_to_voice:
            return False
        if self.expires_at and self.expires_at <= utc_now():
            return False
        return self.purpose.strip() == requested_purpose.strip()


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    version: str
