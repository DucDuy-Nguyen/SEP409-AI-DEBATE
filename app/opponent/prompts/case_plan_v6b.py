"""
Prompt Case Planning v6b — THI NGHIEM "ganh nang chung minh" (A/B voi v5, dev log muc 2.15). v5 (mac dinh) va v6 GIU
NGUYEN.

Ly do (muc 2.13, ket qua v6): cach hieu chuan cua motion "value" viet TRUNG LAP ("Cân nhắc tổng thể tác hại và lợi
ích…") lam mat chieu khang dinh -> model bao ve chinh viec "can nhac" (V1 pro lan 5: "phe Đề xuất thắng vì đưa ra hướng
tiếp cận cân bằng"). v6b noi RO moi phe phai chung minh dieu gi.

= v6, CHI thay khoi cach hieu (quy tac 1) bang (nguyen van spec):
    Kiến nghị: '{motion}'.
    Phe Đề xuất phải chứng minh: {burden_pro}
    Phe Phản đối phải chứng minh: {burden_con}
    BẠN là phe {ai_side_label}. Mọi luận điểm và phần cân nhắc của bạn phải chứng minh: {burden của phe bạn}
Giu: 2 cau KHONG ve cach hieu cua quy tac 1 v5 (phe De xuat, nhu v6), module theo motion_type (quy tac 2), quy tac
3..14. Chi dung khi session co motion_type + burden_pro + burden_con. Code (service) GHI DE case_file.motion_reading =
burden cua phe AI (log neu model tra khac).
"""
from app.opponent.models import DebateSide, MotionType, OpponentDifficulty
from app.opponent.prompts.case_plan_v3 import (  # noqa: F401 — build_response_schema dung chung
    _OUTPUT_EXAMPLE,
    ARGUMENT_COUNT_BY_DIFFICULTY,
    SIDE_LABEL,
    build_response_schema,
)
from app.opponent.prompts.case_plan_v6 import MOTION_TYPE_MODULE, build_prompt_with_rule_1  # noqa: F401

PROMPT_VERSION = "case_plan_v6b"

# Nguyen van spec.
BURDEN_RULE = (
    "Kiến nghị: '{motion}'.\n"
    "Phe Đề xuất phải chứng minh: {burden_pro}\n"
    "Phe Phản đối phải chứng minh: {burden_con}\n"
    "BẠN là phe {ai_side_label}. Mọi luận điểm và phần cân nhắc của bạn phải chứng minh: {ai_burden}"
)
_OUTPUT_EXAMPLE_V6B = {
    **_OUTPUT_EXAMPLE, "motion_reading": "<chép NGUYÊN VĂN điều phe bạn phải chứng minh ở quy tắc 1>",
}


def burden_of(ai_side: DebateSide, burden_pro: str, burden_con: str) -> str:
    return burden_pro if DebateSide(ai_side) == DebateSide.PRO else burden_con


def build_case_plan_prompt(
    motion: str,
    ai_side: DebateSide,
    learner_side: DebateSide,
    difficulty: OpponentDifficulty,
    motion_type: MotionType | None = None,
    burden_pro: str | None = None,
    burden_con: str | None = None,
) -> tuple[str, str]:
    if motion_type is None or not burden_pro or not burden_con:
        raise ValueError("case_plan_v6b can motion_type, burden_pro va burden_con")
    rule_1 = BURDEN_RULE.format(
        motion=motion, burden_pro=burden_pro, burden_con=burden_con, ai_side_label=SIDE_LABEL[ai_side],
        ai_burden=burden_of(ai_side, burden_pro, burden_con),
    )
    return build_prompt_with_rule_1(motion, ai_side, learner_side, difficulty, motion_type, rule_1, _OUTPUT_EXAMPLE_V6B)
