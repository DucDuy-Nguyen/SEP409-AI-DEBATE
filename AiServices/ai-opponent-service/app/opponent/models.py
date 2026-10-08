"""
SQLAlchemy ORM cho module AI Opponent — 5 bang:

- opponent_sessions   : 1 phien luyen tap voi AI doi thu, gan voi 1 session ben Main Flow qua
                        external_session_id (khong FK — khac he thong).
- opponent_case_files : "ho so lap luan" AI chuan bi truoc tran (Case Planning), luu JSONB.
                        MOI session DUNG 1 case file (UNIQUE session_id), khong co phien ban.
- opponent_llm_calls  : log TUNG lan goi LLM (ke ca lan loi/retry) de debug + do chat luong
                        prompt ve sau (giong cach Evaluation service do agreement rate).
- opponent_speeches   : snapshot MOI bai noi trong tran (learner do Main Flow gui + AI), 1 dong / luot.
- opponent_turns      : metadata sinh bai noi cua AI (mode, bo sinh, model, token...), tro toi opponent_speeches.
"""
import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class DebateSide(str, enum.Enum):
    PRO = "pro"
    CON = "con"


class OpponentDifficulty(str, enum.Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class SessionStatus(str, enum.Enum):
    CREATED = "created"  # chi con o du lieu cu (Phase 1 ban dau); session moi tao thang o PLANNING
    PLANNING = "planning"  # dang goi LLM sinh case file
    READY = "ready"  # da co case file hop le
    FAILED = "failed"  # lan Case Planning gan nhat that bai (co the goi lai)


class LLMCallPurpose(str, enum.Enum):
    CASE_PLAN = "case_plan"
    STANCE_REVIEW = "stance_review"  # trong tai trung lap kiem tra phe (stance_reviewer.py)
    TURN = "turn"  # sinh bai noi cua AI trong tran (Giai doan 3)


# Format tran: xem match_format.py (enum dat o day vi dung lam kieu cot DB).
class RoundType(str, enum.Enum):
    OPENING = "opening"
    REBUTTAL = "rebuttal"
    CLOSING = "closing"


class Speaker(str, enum.Enum):
    LEARNER = "learner"
    AI = "ai"


class TurnMode(str, enum.Enum):
    """Che do sinh bai noi cua AI (match_format.turn_mode)."""

    OPENING_FIRST = "opening_first"  # AI pro, luot 1: chua co bai noi nao cua learner
    OPENING_REPLY = "opening_reply"  # AI con, luot 2: mo man sau mo man cua learner
    REBUTTAL = "rebuttal"  # luot 3 hoac 4
    CLOSING = "closing"  # luot 5 hoac 6


class ReviewerVerdict(str, enum.Enum):
    """Ket luan cua code (khong phai LLM) sau khi so position reviewer tra ve voi phe mong doi."""

    PASS = "pass"  # moi muc dung phe
    SIDE_FLIP = "side_flip"  # co it nhat 1 muc nguoc phe -> output khong hop le
    UNCLEAR = "unclear"  # co muc "khong_ro" (hoac reviewer loi) nhung khong muc nao nguoc phe -> chi canh bao


def _pg_enum(enum_cls: type[enum.Enum], name: str) -> Enum:
    # Luu VALUE ("pro") thay vi NAME ("PRO") de DB va API contract dung chung 1 gia tri.
    return Enum(enum_cls, name=name, values_callable=lambda e: [m.value for m in e])


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )


def _created_at() -> Mapped[datetime]:
    # clock_timestamp (khong phai now()): now() co dinh theo transaction, nhieu row
    # tao trong cung 1 transaction se trung created_at -> sap xep "ban moi nhat" sai.
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp())


class OpponentSession(Base):
    __tablename__ = "opponent_sessions"
    # eager_defaults: lay gia tri server-side (id, created_at, updated_at) qua RETURNING,
    # tranh lazy-load ngam (khong duoc phep voi AsyncSession).
    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (
        UniqueConstraint("external_session_id", name="uq_opponent_sessions_external_session_id"),
        CheckConstraint("learner_side <> ai_side", name="ck_opponent_sessions_sides_differ"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    # id session ben Main Flow. Moi route deu dung id nay trong path.
    external_session_id: Mapped[str] = mapped_column(Text, nullable=False)
    motion: Mapped[str] = mapped_column(Text, nullable=False)
    ai_side: Mapped[DebateSide] = mapped_column(_pg_enum(DebateSide, "debate_side"), nullable=False)
    learner_side: Mapped[DebateSide] = mapped_column(_pg_enum(DebateSide, "debate_side"), nullable=False)
    difficulty: Mapped[OpponentDifficulty] = mapped_column(
        _pg_enum(OpponentDifficulty, "opponent_difficulty"), nullable=False
    )
    language: Mapped[str] = mapped_column(String(10), nullable=False, server_default="vi")
    status: Mapped[SessionStatus] = mapped_column(
        _pg_enum(SessionStatus, "opponent_session_status"),
        nullable=False,
        default=SessionStatus.CREATED,
        server_default=SessionStatus.CREATED.value,
    )
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp(), onupdate=func.clock_timestamp()
    )

    case_file: Mapped["OpponentCaseFile | None"] = relationship(
        back_populates="session", uselist=False, cascade="all, delete-orphan", passive_deletes=True
    )


class OpponentCaseFile(Base):
    __tablename__ = "opponent_case_files"
    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (UniqueConstraint("session_id", name="uq_opponent_case_files_session_id"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("opponent_sessions.id", ondelete="CASCADE"), nullable=False
    )
    # Noi dung da validate qua schemas.CaseFile — luu dang JSONB de truy van duoc ve sau.
    content: Mapped[dict] = mapped_column(JSONB, nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(50), nullable=False)
    llm_provider: Mapped[str] = mapped_column(String(50), nullable=False)
    llm_model: Mapped[str] = mapped_column(String(100), nullable=False)
    temperature: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = _created_at()

    session: Mapped[OpponentSession] = relationship(back_populates="case_file")


class OpponentLLMCall(Base):
    __tablename__ = "opponent_llm_calls"
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[uuid.UUID] = _uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("opponent_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    purpose: Mapped[LLMCallPurpose] = mapped_column(_pg_enum(LLMCallPurpose, "llm_call_purpose"), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(50), nullable=False)
    llm_provider: Mapped[str] = mapped_column(String(50), nullable=False)
    llm_model: Mapped[str] = mapped_column(String(100), nullable=False)
    temperature: Mapped[float] = mapped_column(Float, nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    user_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    raw_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    # Cum "bang chung mo ho" tim thay trong case file hop le (service.detect_vague_evidence), moi phan tu
    # {"phrase", "field"}. Dong cu (truoc 2026-09-26 toi) la list chuoi, chi co cum khong co truong.
    # NULL = khong quet (output khong hop le / loi goi LLM); [] = da quet, khong co.
    vague_evidence: Mapped[list[dict] | None] = mapped_column(JSONB, nullable=True)
    # Ket qua Stance Reviewer cho OUTPUT cua dong nay (dong purpose=case_plan da parse hop le).
    # NULL = khong review (output khong hop le truoc do / reviewer tat). Phase 3 dung lai cho tung luot noi.
    reviewer_verdict: Mapped[ReviewerVerdict | None] = mapped_column(
        _pg_enum(ReviewerVerdict, "reviewer_verdict"), nullable=True
    )
    reviewer_detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Loai that bai cua dong nay (NULL = thanh cong). Gia tri: provider_error, rate_limited, schema_rejected,
    # invalid_json, schema_validation, argument_count, banned_phrase, side_flip, budget_exceeded, reviewer_error,
    # empty_output (bai noi rong, baseline), word_count (bai noi ngoai khoang do dai, turn_full_v*),
    # truncated_max_tokens (output rong / bi cat vi het max_tokens, turn_full_v*).
    failure_kind: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # Phan hoi DA GUI cho lan thu ke tiep vi output cua dong nay khong hop le (NULL = khong retry tu dong nay).
    retry_feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Token thuc te provider tinh (usage); NULL neu loi / provider khong tra. tokens_out cua gpt-oss gom token suy luan.
    tokens_in: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_out: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Dong 429: thoi gian DA CHO truoc khi goi lai (retry-after / "try again in Xs" + jitter). NULL = khong cho.
    rate_limit_wait_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Groq tu choi schema nhung ten truong go sai (<= 3 ky tu) da duoc TU SUA, khong goi lai LLM:
    # {"event": "key_repaired", "renames": [{"path", "from", "to"}], "provider_error": ...}. NULL = khong sua.
    key_repairs: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Loi goi sinh bai noi (purpose=turn): tro toi luot AI da luu. NULL voi Case Planning / stance review, va voi
    # loi goi cua luot sinh THAT BAI (chua co dong opponent_turns) — khi do tim theo session_id + purpose.
    # Bai noi (turn_full_v1) — kiem tra CHI LOG, khong reject: {"numbers_without_gia_su": [cau], "em_pronoun": [cau]}.
    # (Bang chung mo ho cua bai noi nam o vague_evidence, nhu Case Planning.) NULL = khong kiem tra.
    speech_checks: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Token suy luan RIENG (da nam trong tokens_out cua gpt-oss) neu provider tra ve; finish_reason cua response
    # ("length" = het max_tokens); reasoning_effort DA GUI (NULL = khong gui, provider dung mac dinh). Migration 0010.
    reasoning_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    finish_reason: Mapped[str | None] = mapped_column(String(30), nullable=True)
    reasoning_effort: Mapped[str | None] = mapped_column(String(10), nullable=True)
    turn_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("opponent_turns.id", ondelete="CASCADE"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = _created_at()


class OpponentSpeech(Base):
    """Snapshot 1 bai noi (learner hoac AI) — tran dau duoc dung lai tu bang nay, khong tu Main Flow."""

    __tablename__ = "opponent_speeches"
    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (
        UniqueConstraint("session_id", "turn_index", name="uq_opponent_speeches_session_turn"),
        CheckConstraint("turn_index BETWEEN 1 AND 6", name="ck_opponent_speeches_turn_index"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("opponent_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    turn_index: Mapped[int] = mapped_column(Integer, nullable=False)
    round_type: Mapped[RoundType] = mapped_column(_pg_enum(RoundType, "debate_round_type"), nullable=False)
    speaker: Mapped[Speaker] = mapped_column(_pg_enum(Speaker, "speech_speaker"), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _created_at()


class OpponentTurn(Base):
    """1 luot noi cua AI: cach sinh ra bai noi (speech_id tro toi noi dung)."""

    __tablename__ = "opponent_turns"
    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (UniqueConstraint("session_id", "turn_index", name="uq_opponent_turns_session_turn"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("opponent_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    speech_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("opponent_speeches.id", ondelete="CASCADE"), nullable=False
    )
    turn_index: Mapped[int] = mapped_column(Integer, nullable=False)
    round_type: Mapped[RoundType] = mapped_column(_pg_enum(RoundType, "debate_round_type"), nullable=False)
    mode: Mapped[TurnMode] = mapped_column(_pg_enum(TurnMode, "turn_mode"), nullable=False)
    generator_version: Mapped[str] = mapped_column(String(50), nullable=False)
    llm_provider: Mapped[str] = mapped_column(String(50), nullable=False)
    llm_model: Mapped[str] = mapped_column(String(100), nullable=False)
    temperature: Mapped[float] = mapped_column(Float, nullable=False)
    # Bo sinh day du (3b) trich tu bai learner; baseline de NULL.
    learner_claims: Mapped[list | dict | None] = mapped_column(JSONB, nullable=True)
    premises: Mapped[list | dict | None] = mapped_column(JSONB, nullable=True)
    target_premise: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Dan y 2-4 y AI noi trong luot (turn_full_v1) — ledger "nhung dieu ban DA khang dinh" cho cac luot sau. Baseline NULL.
    ai_points: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    word_count: Mapped[int] = mapped_column(Integer, nullable=False)
    # Tong cua moi lan goi LLM cua luot (ke ca lan thu lai).
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    # Tong thoi gian DA CHO 429 trong luot (ms; 0 = khong cho). Migration 0011, muc 2.12.
    rate_limit_wait_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_in: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_out: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = _created_at()
