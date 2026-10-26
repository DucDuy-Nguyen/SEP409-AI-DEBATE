"""
Cac model du lieu (Pydantic) cho request/response cua AI Evaluator.

Thiet ke output dang JSON co cau truc (khong dung tag [[ ]] nhu ban prompt
demo truoc) vi JSON de parse chac chan hon trong code that, giam rui ro
regex parse sai khi LLM tra loi khong dung dinh dang tuyet doi.
"""
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

# Phien ban cong thuc diem tong, de lich su va trung binh Session khong tron hai thang diem
# (docs/AI_DEVELOPMENT_LOG.md muc 3.14). Ban ghi cu khong co truong nay -> mac dinh la LEGACY.
SCORING_VERSION_LEGACY = "v1_5x20"  # 5 tieu chi x 20%: (tong 5 tieu chi / 25) * 10
SCORING_VERSION_CURRENT = "v2_4x25"  # Logic/Evidence/Relevance/Structure x 25%, Persuasiveness 0%


class DebateSide(str, Enum):
    PRO = "pro"
    CON = "con"


class DebateStage(str, Enum):
    OPENING = "opening"
    REBUTTAL = "rebuttal"
    CLOSING = "closing"


class ArgumentEvaluationRequest(BaseModel):
    """Input: 1 luot lap luan cua learner can duoc cham diem."""

    motion: str = Field(..., description="Chu de tranh bien, vi du: 'THBT social media does more harm than good'")
    side: DebateSide = Field(..., description="Learner dang dung ve phia Pro hay Con")
    stage: DebateStage = Field(default=DebateStage.REBUTTAL, description="Giai doan cua lap luan")
    argument_text: str = Field(..., min_length=1, description="Noi dung lap luan can cham")
    opponent_argument_text: Optional[str] = Field(
        default=None,
        description="Lap luan cua doi phuong ngay truoc do (neu co) — giup danh gia tinh relevance/rebuttal",
    )

    @field_validator("argument_text")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("argument_text khong duoc de trong")
        return v


class CriterionScore(BaseModel):
    """
    Diem cho 1 tieu chi trong rubric (logic, evidence, relevance, structure, persuasiveness).

    Khong co field 'weight' trong response: trong so nam trong RUBRIC (app/prompts/evaluator_prompt.py).
    Tu 2026-10: Logic, Evidence, Relevance, Structure moi tieu chi 25% diem tong; Persuasiveness van
    nam trong `criteria` (co score + reasoning) nhu mot nhan dinh tong the nhung co trong so 0, KHONG
    cong vao diem tong (docs/AI_DEVELOPMENT_LOG.md muc 3.14).
    """

    name: str
    score: int = Field(..., ge=1, le=5)
    reasoning: str = Field(..., description="Giai thich TAI SAO cham diem nay — bat buoc, khong duoc de trong")


class ArgumentEvaluationResult(BaseModel):
    """
    Output: ket qua cham diem day du cho 1 luot lap luan.

    overall_score: thang 0-10, LUON duoc TINH BANG CONG THUC tu cac tieu chi con:
    overall_score = 2 x Sum(trong so x diem tieu chi), chi 4 tieu chi Logic/Evidence/Relevance/
    Structure x 25% (Persuasiveness khong tinh) — gia tri TAT DINH (deterministic),
    tinh 100% trong app/services/evaluator.py, KHONG doc/dung gia tri overall_score
    (neu co) ma LLM tra ve trong JSON. Du an co thu doi sang de AI tu cham 1
    overall_score doc lap (holistic) trong 1 giai doan, nhung thi nghiem so sanh
    truc tiep 2 cach tinh tren cung du lieu (scripts/compare_overall_score_methods.py)
    cho thay 2 cach NGANG NHAU ve do khop nguoi cham that (r=0.585 vs r=0.601,
    n=22), trong khi Holistic lai KHONG ON DINH giua cac lan cham (xem case
    arg35720 trong docs/AI_DEVELOPMENT_LOG.md) — nen da DAO NGUOC lai ve cong
    thuc de uu tien tinh on dinh + minh bach + kiem chung duoc.
    """

    overall_score: float = Field(
        ..., ge=0, le=10, description="Tinh bang cong thuc tu 4 tieu chi tinh diem (Persuasiveness khong tinh), KHONG doc tu gia tri LLM tu tra ve"
    )
    overall_reasoning: str = Field(
        ...,
        description=(
            "Nhan xet TONG HOP ngan gon ve chat luong lap luan, dua tren 5 tieu chi con — "
            "bat buoc, khong duoc de trong, giu nguyen tac Chain-of-Thought di kem moi ket qua cham diem"
        ),
    )
    criteria: list[CriterionScore]
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(
        default_factory=list, description="Goi y cu the de learner cai thien luot lap luan tiep theo"
    )
    raw_model_output: Optional[str] = Field(
        default=None, description="Output tho tu LLM — luu de debug / audit, khong hien thi cho learner"
    )
    scoring_version: str = Field(
        default=SCORING_VERSION_LEGACY,
        description="Phien ban cong thuc diem tong (v1_5x20 cu, v2_4x25 moi); khong tron hai thang khi tinh Session",
    )


# ============================================================================
# ROUND-LEVEL: cham diem toan bo 1 round (vi du: toan bo giai doan Rebuttal),
# gom nhieu luot noi qua lai giua learner va doi phuong (AI hoac nguoi thuc).
# ============================================================================


class TurnSpeaker(str, Enum):
    LEARNER = "learner"
    OPPONENT = "opponent"


class ArgumentTurn(BaseModel):
    """1 luot noi trong round — khong quan tam doi phuong la AI hay nguoi thuc,
    chi can la 1 doan text, dung chung logic cho ca Practice (vs AI) va
    Competition (vs learner khac)."""

    speaker: TurnSpeaker
    text: str = Field(..., min_length=1)


class RoundEvaluationRequest(BaseModel):
    """Input: toan bo cac luot noi trong 1 round (1 giai doan) cua 1 learner."""

    motion: str
    side: DebateSide = Field(..., description="Phia cua learner dang duoc cham (khong phai doi phuong)")
    stage: DebateStage
    turns: list[ArgumentTurn] = Field(..., min_length=1, description="Cac luot noi theo dung thu tu thoi gian")

    @field_validator("turns")
    @classmethod
    def must_have_learner_turn(cls, v: list[ArgumentTurn]) -> list[ArgumentTurn]:
        if not any(t.speaker == TurnSpeaker.LEARNER for t in v):
            raise ValueError("Round phai co it nhat 1 luot noi cua learner de cham diem")
        return v


class RoundEvaluationResult(BaseModel):
    """
    Output: cham diem toan bo 1 round, khong phai trung binh don gian cua tung luot —
    LLM danh gia TINH NHAT QUAN xuyen suot round (giu vung lap truong, phan ung tot
    voi phan bien cua doi phuong qua cac luot, khong chi cham rieng le tung cau).

    round_score: thang 0-10, LUON duoc TINH BANG CONG THUC tu cac tieu chi con:
    round_score = 2 x Sum(trong so x diem tieu chi), chi 4 tieu chi Logic/Evidence/Relevance/
    Structure x 25% (Persuasiveness khong tinh) — gia tri TAT DINH (deterministic),
    KHONG doc/dung gia tri "round_score" (neu co) ma LLM tra ve trong JSON. Ap
    dung dung nguyen tac da chot cho ArgumentEvaluationResult.overall_score (xem
    docs/AI_DEVELOPMENT_LOG.md muc 3.8) sau khi AI tung tra round_score=14.0
    (vuot thang 0-10) gay ValidationError phai retry.
    """

    stage: DebateStage
    round_score: float = Field(
        ..., ge=0, le=10, description="Tinh bang cong thuc tu 4 tieu chi tinh diem (Persuasiveness khong tinh), KHONG doc tu gia tri LLM tu tra ve"
    )
    criteria: list[CriterionScore]
    consistency_note: str = Field(
        ..., description="Nhan xet ve tinh nhat quan cua learner xuyen suot round (co giu vung lap truong khong)"
    )
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    raw_model_output: Optional[str] = None
    scoring_version: str = Field(
        default=SCORING_VERSION_LEGACY,
        description="Phien ban cong thuc diem tong (v1_5x20 cu, v2_4x25 moi); Session ghim theo round dau tien",
    )


# ============================================================================
# SESSION-LEVEL: tong hop diem tu nhieu Round (Opening + Rebuttal + Closing)
# thanh 1 bao cao tong ket cho ca phien tranh bien (feedback report).
# ============================================================================


class SessionEvaluationRequest(BaseModel):
    """
    Input: danh sach ket qua Round DA CHAM XONG (tu RoundEvaluationResult o tren)
    cho 1 learner trong 1 phien tranh bien. Diem tong duoc tinh TOAN HOC (trung
    binh cac round_score, khong goi LLM cham lai lan nua) — LLM chi duoc dung
    de tong hop phan nhan xet dinh tinh (progress, strengths, weaknesses chung),
    tranh ton chi phi cham lai va dam bao diem tong minh bach, kiem chung duoc.
    """

    motion: str
    side: DebateSide
    rounds: list[RoundEvaluationResult] = Field(..., min_length=1)


class SessionEvaluationResult(BaseModel):
    """Output: bao cao tong ket ca phien tranh bien."""

    overall_score: float = Field(..., ge=0, le=10, description="Trung binh cac round_score, tinh toan hoc")
    stage_breakdown: dict[str, float] = Field(
        ..., description="Diem tung giai doan, vi du {'opening': 7.2, 'rebuttal': 6.8, 'closing': 8.0}"
    )
    progress_trend: str = Field(..., description="Nhan xet xu huong tien bo/giam sut qua cac giai doan")
    overall_strengths: list[str] = Field(default_factory=list)
    overall_weaknesses: list[str] = Field(default_factory=list)
    overall_suggestions: list[str] = Field(default_factory=list)
    raw_model_output: Optional[str] = None
    scoring_version: str = Field(
        default=SCORING_VERSION_LEGACY, description="Phien ban cong thuc diem tong cua ROUND DAU TIEN (Session ghim theo round dau; khong kiem tra/loai cac round khac phien ban)"
    )


# ============================================================================
# COACHING (Argument-level + Round-level): goi y SAU KHI da cham — phuong phap
# cai thien theo tieu chi yeu + huong phat trien chinh y cua learner. KHONG
# cham lai, KHONG viet lai bai thay learner.
# ============================================================================

# Khong import RUBRIC tu app.prompts de tranh import vong (evaluator_prompt.py
# import schemas.py) — 5 = so tieu chi trong RUBRIC.
_RUBRIC_CRITERIA_COUNT = 5


def _check_all_criteria(criteria: list[CriterionScore], source_endpoint: str) -> None:
    if len(criteria) != _RUBRIC_CRITERIA_COUNT:
        raise ValueError(
            f"evaluation.criteria phai co du {_RUBRIC_CRITERIA_COUNT} tieu chi "
            f"(nhan duoc {len(criteria)}) — hay truyen nguyen ket qua tu {source_endpoint}"
        )


class ArgumentCoachingRequest(BaseModel):
    """
    Input: bai goc + ket qua /evaluate DA CO, truyen lai nguyen ven (giong cach
    /evaluate/session nhan lai ket qua Round) — khong cham lai, chi 1 lan goi LLM
    va nhat quan voi diem learner da thay.
    """

    request: ArgumentEvaluationRequest
    evaluation: ArgumentEvaluationResult

    @field_validator("evaluation")
    @classmethod
    def must_have_all_criteria(cls, v: ArgumentEvaluationResult) -> ArgumentEvaluationResult:
        _check_all_criteria(v.criteria, "/evaluate")
        return v


class RoundCoachingRequest(BaseModel):
    """Input: round goc + ket qua /evaluate/round DA CO, truyen lai nguyen ven."""

    request: RoundEvaluationRequest
    evaluation: RoundEvaluationResult

    @field_validator("evaluation")
    @classmethod
    def must_have_all_criteria(cls, v: RoundEvaluationResult) -> RoundEvaluationResult:
        _check_all_criteria(v.criteria, "/evaluate/round")
        return v

    @model_validator(mode="after")
    def stage_must_match(self) -> "RoundCoachingRequest":
        # Chan ghep nham ket qua cua round khac (vi du request opening + evaluation rebuttal).
        if self.request.stage != self.evaluation.stage:
            raise ValueError(
                f"request.stage ({self.request.stage.value}) khac evaluation.stage "
                f"({self.evaluation.stage.value}) — evaluation phai la ket qua cham cua chinh round nay"
            )
        return self


class CriterionCoaching(BaseModel):
    """Goi y cai thien cho 1 tieu chi yeu."""

    name: str
    current_score: int = Field(
        ..., ge=1, le=5, description="Lay tu ket qua cham da co, KHONG doc tu gia tri LLM tu tra ve"
    )
    diagnosis: str = Field(..., description="Van de cu the cua tieu chi nay trong chinh bai nay")
    methods: list[str] = Field(..., min_length=1, description="2-3 ky thuat cu the de cai thien")
    application: str = Field(
        ..., description="Cach ap dung vao chinh bai nay — goi y huong, KHONG viet lai bai thay learner"
    )


class IdeaDevelopment(BaseModel):
    """Goi y phat trien chinh luan diem learner da neu."""

    core_claim: str = Field(..., description="Tom tat luan diem chinh learner da neu")
    directions: list[str] = Field(..., min_length=1, description="2-4 huong dao sau luan diem")
    evidence_to_look_for: list[str] = Field(
        default_factory=list,
        description="LOAI dan chung nen tim — mo ta loai, KHONG phai so lieu/nguon cu the (tranh bia)",
    )


class CoachingResult(BaseModel):
    """Output: goi y sau khi cham — dung chung cho ca cap Argument va Round."""

    focus_criteria: list[CriterionCoaching]
    idea_development: IdeaDevelopment
    raw_model_output: Optional[str] = Field(
        default=None, description="Output tho tu LLM — luu de debug / audit, khong hien thi cho learner"
    )
