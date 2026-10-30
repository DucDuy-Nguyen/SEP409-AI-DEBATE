"""
Prompt Case Planning v7 — THI NGHIEM kiem chung "ganh nang chung minh giam lat phe" (A/B voi v5, dev log muc 2.16).
v5 (mac dinh), v6, v6b GIU NGUYEN.

Ly do (muc 2.15, phat hien phu SAU khi co du lieu): side_flip 0 luot o v6b vs 2 luot o v5. v6b gom NHIEU thay doi
(bo phan tu dien giai, module theo motion_type, ghi de motion_reading, khoi ganh nang) -> v7 TACH RIENG khoi ganh nang.

= v5 NGUYEN VAN (system prompt giu nguyen, ke ca SIDE_RULE; khong module motion_type; KHONG ghi de motion_reading — model
van tu viet nhu v5), chi CHEN khoi sau (nguyen van spec) ngay sau dong "KIẾN NGHỊ: …" cua user prompt:
    Phe Đề xuất phải chứng minh: {burden_pro}
    Phe Phản đối phải chứng minh: {burden_con}
    BẠN là phe {ai_side_label}. Mọi luận điểm và phần cân nhắc của bạn phải chứng minh: {burden của phe bạn}
Chi dung khi session co burden_pro + burden_con (motion_type KHONG can).
"""
from app.opponent.models import DebateSide, OpponentDifficulty
from app.opponent.prompts import case_plan_v5
from app.opponent.prompts.case_plan_v3 import (  # noqa: F401 — build_response_schema dung chung
    ARGUMENT_COUNT_BY_DIFFICULTY,
    SIDE_LABEL,
    build_response_schema,
)

PROMPT_VERSION = "case_plan_v7"

# Nguyen van spec.
BURDEN_BLOCK = (
    "Phe Đề xuất phải chứng minh: {burden_pro}\n"
    "Phe Phản đối phải chứng minh: {burden_con}\n"
    "BẠN là phe {ai_side_label}. Mọi luận điểm và phần cân nhắc của bạn phải chứng minh: {ai_burden}"
)


def burden_of(ai_side: DebateSide, burden_pro: str, burden_con: str) -> str:
    return burden_pro if DebateSide(ai_side) == DebateSide.PRO else burden_con


def build_case_plan_prompt(
    motion: str,
    ai_side: DebateSide,
    learner_side: DebateSide,
    difficulty: OpponentDifficulty,
    burden_pro: str | None = None,
    burden_con: str | None = None,
) -> tuple[str, str]:
    if not burden_pro or not burden_con:
        raise ValueError("case_plan_v7 can burden_pro va burden_con")
    system_prompt, user_prompt = case_plan_v5.build_case_plan_prompt(motion, ai_side, learner_side, difficulty)
    motion_line = f"KIẾN NGHỊ: {motion}"
    assert user_prompt.startswith(motion_line + "\n"), "v5 user prompt phai bat dau bang dong kien nghi"
    block = BURDEN_BLOCK.format(
        burden_pro=burden_pro, burden_con=burden_con, ai_side_label=SIDE_LABEL[ai_side],
        ai_burden=burden_of(ai_side, burden_pro, burden_con),
    )
    return system_prompt, motion_line + "\n" + block + user_prompt[len(motion_line):]
