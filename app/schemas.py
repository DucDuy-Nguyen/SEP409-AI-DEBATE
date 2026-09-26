"""
Cac model du lieu (Pydantic) cho request/response cua AI Evaluator.

Thiet ke output dang JSON co cau truc (khong dung tag [[ ]] nhu ban prompt
demo truoc) vi JSON de parse chac chan hon trong code that, giam rui ro
regex parse sai khi LLM tra loi khong dung dinh dang tuyet doi.
"""
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


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

    Khong co field 'weight' rieng vi ca 5 tieu chi co trong so BANG NHAU (20% moi tieu chi) —
    xem RUBRIC trong app/prompts/evaluator_prompt.py va docstring giai thich ly do (dua tren
    Wachsmuth et al. 2017, khong co can cu de uu tien tieu chi nao hon tieu chi nao).
    """

    name: str
    score: int = Field(..., ge=1, le=5)
    reasoning: str = Field(..., description="Giai thich TAI SAO cham diem nay — bat buoc, khong duoc de trong")


class ArgumentEvaluationResult(BaseModel):
    """
    Output: ket qua cham diem day du cho 1 luot lap luan.

    overall_score: thang 0-10, LUON duoc TINH BANG CONG THUC tu 5 tieu chi con:
    overall_score = (tong 5 tieu chi / 25) * 10 — gia tri TAT DINH (deterministic),
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
        ..., ge=0, le=10, description="Tinh bang cong thuc tu 5 tieu chi con, KHONG doc tu gia tri LLM tu tra ve"
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

    round_score: thang 0-10, LUON duoc TINH BANG CONG THUC tu 5 tieu chi con:
    round_score = (tong 5 tieu chi / 25) * 10 — gia tri TAT DINH (deterministic),
    KHONG doc/dung gia tri "round_score" (neu co) ma LLM tra ve trong JSON. Ap
    dung dung nguyen tac da chot cho ArgumentEvaluationResult.overall_score (xem
    docs/AI_DEVELOPMENT_LOG.md muc 3.8) sau khi AI tung tra round_score=14.0
    (vuot thang 0-10) gay ValidationError phai retry.
    """

    stage: DebateStage
    round_score: float = Field(
        ..., ge=0, le=10, description="Tinh bang cong thuc tu 5 tieu chi con, KHONG doc tu gia tri LLM tu tra ve"
    )
    criteria: list[CriterionScore]
    consistency_note: str = Field(
        ..., description="Nhan xet ve tinh nhat quan cua learner xuyen suot round (co giu vung lap truong khong)"
    )
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    raw_model_output: Optional[str] = None


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
