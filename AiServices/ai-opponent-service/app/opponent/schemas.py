"""
Pydantic models cho request/response cua module AI Opponent + schema case_file.

Quy uoc giong Evaluation service (AI_DEVELOPMENT_LOG muc 2.4): TEN FIELD JSON giu
tieng Anh (API contract), NOI DUNG sinh ra bang tieng Viet.
"""
import unicodedata
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.opponent.models import DebateSide, OpponentDifficulty, RoundType, SessionStatus, TurnMode

# Moi CaseArgument.example phai bat dau bang cum nay (prompt v3).
EXAMPLE_PREFIX = "Giả sử"

# ---------------------------------------------------------------------------
# case_file — output cua Case Planning (LLM phai tra ve dung schema nay)
# ---------------------------------------------------------------------------


class Definition(BaseModel):
    term: str = Field(..., min_length=1)
    meaning: str = Field(..., min_length=1)


class CaseArgument(BaseModel):
    """1 luan diem AI se dung trong tran (claim -> reasoning -> example -> impact)."""

    id: str = Field(..., min_length=1, description="Ma luan diem, vd 'A1'")
    title: str = Field(..., min_length=1)
    claim: str = Field(..., min_length=1)
    reasoning: str = Field(..., min_length=1)
    example: str = Field(
        ...,
        min_length=1,
        description="Tinh huong gia dinh, BAT BUOC bat dau bang 'Giả sử' (KHONG so lieu/trich dan)",
    )
    impact: str = Field(..., min_length=1, description="Tai sao luan diem nay quan trong")

    @field_validator("example")
    @classmethod
    def example_starts_with_gia_su(cls, v: str) -> str:
        # NFC: tieng Viet co the o dang to hop (NFD) — "Giả sử" nhin giong nhau nhung khac byte.
        v = unicodedata.normalize("NFC", v).strip()
        if not v.startswith(EXAMPLE_PREFIX):
            raise ValueError(f"example phai bat dau bang '{EXAMPLE_PREFIX}'")
        return v


class AnticipatedArgument(BaseModel):
    """
    Luan diem AI du doan learner (phia doi dien) se dua ra + huong phan bien da chuan bi.
    `learner_claim` (truoc v3 la `opponent_claim` — de nham voi ten module "opponent" = AI).
    """

    id: str = Field(..., min_length=1, description="Ma, vd 'O1'")
    learner_claim: str = Field(..., min_length=1)
    planned_response: str = Field(..., min_length=1)


class CaseFile(BaseModel):
    """
    Khong co `stance`: phe cua AI lay tu session (ai_side), khong de LLM tu mo ta.
    So luan diem CHINH XAC theo do kho duoc kiem tra o service (schema khong biet do kho);
    o day chi chan bien 2..3.
    """

    # Truoc 2026-09-29 ten la `motion_interpretation`: gpt-oss-120b lap lai loi go "motion_interinterpretation"
    # (mau v2 so 2 + 3/4 lan Groq tu choi schema o batch v4) -> doi sang ten ngan, it token lap (migration 0007).
    motion_reading: str = Field(..., min_length=1, description="Cach AI hieu/gioi han pham vi motion")
    definitions: list[Definition] = Field(default_factory=list, max_length=5)
    arguments: list[CaseArgument] = Field(..., min_length=2, max_length=3)
    anticipated_opponent_arguments: list[AnticipatedArgument] = Field(..., min_length=2, max_length=5)
    weighing: str = Field(..., min_length=1, description="Vi sao phia AI thang khi can nhac tong the")

    @model_validator(mode="after")
    def unique_ids(self) -> "CaseFile":
        ids = [a.id for a in self.arguments] + [a.id for a in self.anticipated_opponent_arguments]
        if len(ids) != len(set(ids)):
            raise ValueError("id cua arguments / anticipated_opponent_arguments bi trung")
        return self


# ---------------------------------------------------------------------------
# API request / response
# ---------------------------------------------------------------------------


class CreateSessionRequest(BaseModel):
    external_session_id: str = Field(..., max_length=200, description="Id session ben Main Flow (khoa idempotent)")
    motion: str = Field(..., max_length=500, description="Chu de tranh bien")
    learner_side: DebateSide
    ai_side: DebateSide
    difficulty: OpponentDifficulty = OpponentDifficulty.MEDIUM
    # Prompt v2 bat buoc noi dung tieng Viet -> chi nhan "vi". Mo rong can prompt moi.
    language: Literal["vi"] = "vi"

    @field_validator("external_session_id", "motion")
    @classmethod
    def not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("khong duoc de trong")
        return v
    # learner_side != ai_side KHONG validate o day: spec yeu cau 400 (Pydantic se tra 422) -> kiem tra o service.


class CreateSessionResponse(BaseModel):
    opponent_session_id: uuid.UUID
    status: SessionStatus


class CaseFileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    session_id: uuid.UUID
    # JSON dung nhu da luu (da validate theo schema cua prompt_version LUC SINH). Khong validate lai
    # bang CaseFile hien tai: validator chat hon (vd "Giả sử" tu v3) se lam GET debug loi 500 voi case file cu.
    content: dict
    prompt_version: str
    llm_provider: str
    llm_model: str
    temperature: float
    created_at: datetime


class SessionResponse(BaseModel):
    """Chi dung cho GET debug."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    external_session_id: str
    motion: str
    ai_side: DebateSide
    learner_side: DebateSide
    difficulty: OpponentDifficulty
    language: str
    status: SessionStatus
    created_at: datetime
    updated_at: datetime
    case_file: CaseFileResponse | None = None


# ---------------------------------------------------------------------------
# Luot tranh luan (Giai doan 3)
# ---------------------------------------------------------------------------


class LearnerSpeechIn(BaseModel):
    turn_index: int
    round_type: RoundType
    text: str = Field(..., max_length=20000)

    @field_validator("text")
    @classmethod
    def normalized_not_blank(cls, v: str) -> str:
        # NFC + strip: so sanh snapshot (idempotent) khong bi lech vi dang to hop dau / khoang trang thua.
        v = unicodedata.normalize("NFC", v).strip()
        if not v:
            raise ValueError("khong duoc de trong")
        return v


class CreateTurnRequest(BaseModel):
    turn_index: int = Field(..., description="Luot cua AI can sinh (1..6, theo match_format)")
    # MOI bai noi cua learner KE TU luot AI truoc do (co the rong). Gui lai bai da luu (cung noi dung) duoc chap nhan.
    new_learner_speeches: list[LearnerSpeechIn] = Field(default_factory=list, max_length=6)


class TurnResponse(BaseModel):
    turn_index: int
    round_type: RoundType
    mode: TurnMode
    speech_text: str

