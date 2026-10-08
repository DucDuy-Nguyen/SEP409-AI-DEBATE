"""
Prompt Case Planning v2 (thay v1 — v1 giu nguyen de doi chieu, KHONG con duoc dung
vi schema v1 co `stance` / `evidence` da bi bo khoi CaseFile).

Thay doi so voi v1:
- Khoa phe: ghi ro phe AI + phe learner, phe AI co dinh.
- `evidence` (list) -> `example` (1 vi du doi thuong hoac tinh huong gia dinh "Giả sử...").
- Bo `stance` (phe lay tu session).
- So luan diem CO DINH theo do kho (easy=2, medium=3, hard=3) — service kiem tra, sai la retry.
- Uu tien boi canh Viet Nam; noi dung luon bang tieng Viet.

Cac cau trong ARGUMENT_RULES / system prompt danh dau "nguyen van" lay DUNG theo spec, khong sua.
"""
import json

from app.opponent.models import DebateSide, OpponentDifficulty

PROMPT_VERSION = "case_plan_v2"

# So luan diem BAT BUOC theo do kho — service.py dung chung hang so nay de validate output.
ARGUMENT_COUNT_BY_DIFFICULTY = {
    OpponentDifficulty.EASY: 2,
    OpponentDifficulty.MEDIUM: 3,
    OpponentDifficulty.HARD: 3,
}

SIDE_LABEL = {
    DebateSide.PRO: "ỦNG HỘ (Proposition)",
    DebateSide.CON: "PHẢN ĐỐI (Opposition)",
}

_DIFFICULTY_GUIDE = {
    OpponentDifficulty.EASY: (
        "DỄ: lập luận đơn giản, dễ hiểu; có thể còn 1 vài lỗ hổng nhỏ để người học (người mới) "
        "có cơ hội phản biện."
    ),
    OpponentDifficulty.MEDIUM: "TRUNG BÌNH: lập luận chặt chẽ ở mức khá, có cơ chế (mechanism) rõ ràng.",
    OpponentDifficulty.HARD: (
        "KHÓ: các luận điểm mạnh nhất có thể, cơ chế chặt chẽ, cân nhắc (weighing) sắc bén, "
        "chủ động chặn trước các phản biện phổ biến."
    ),
}

_OUTPUT_EXAMPLE = {
    "motion_interpretation": "<cách bạn hiểu kiến nghị, phạm vi, giả định hợp lý>",
    "definitions": [{"term": "<thuật ngữ trong kiến nghị>", "meaning": "<định nghĩa bạn dùng>"}],
    "arguments": [
        {
            "id": "A1",
            "title": "<tên ngắn của luận điểm>",
            "claim": "<khẳng định chính>",
            "reasoning": "<cơ chế / chuỗi suy luận vì sao khẳng định đúng>",
            "example": "<1 ví dụ đời thường, HOẶC tình huống giả định bắt đầu bằng \"Giả sử...\">",
            "impact": "<vì sao điều này quan trọng, ảnh hưởng đến ai, mức độ>",
        }
    ],
    "anticipated_opponent_arguments": [
        {
            "id": "O1",
            "opponent_claim": "<luận điểm mạnh nhất phe người học có thể đưa ra>",
            "planned_response": "<hướng phản biện bạn đã chuẩn bị>",
        }
    ],
    "weighing": "<vì sao khi cân nhắc tổng thể, phe bạn thắng>",
}


def build_case_plan_prompt(
    motion: str,
    ai_side: DebateSide,
    learner_side: DebateSide,
    difficulty: OpponentDifficulty,
) -> tuple[str, str]:
    ai_side_label = SIDE_LABEL[ai_side]
    learner_side_label = SIDE_LABEL[learner_side]
    n_args = ARGUMENT_COUNT_BY_DIFFICULTY[difficulty]

    system_prompt = f"""Bạn là một debater giàu kinh nghiệm, đóng vai ĐỐI THỦ của một người học \
trên nền tảng luyện tập tranh biện ADPP. Nhiệm vụ hiện tại: CHUẨN BỊ CASE (hồ sơ lập luận) \
trước khi trận đấu bắt đầu — chưa nói với người học, chỉ lập kế hoạch.

Bạn thuộc phe {ai_side_label}. Người học thuộc phe {learner_side_label}. Phe của bạn là CỐ ĐỊNH và không bao giờ thay đổi.

QUY TẮC BẮT BUỘC:
1. KHÔNG bịa số liệu thống kê, tỷ lệ phần trăm, tên nghiên cứu, tên tổ chức hay trích dẫn cụ thể. Chỉ dùng lý lẽ logic, ví dụ đời thường, hoặc tình huống giả định được ghi rõ là giả định.
2. Ưu tiên bối cảnh Việt Nam (giáo dục, gia đình, xã hội Việt Nam) khi phù hợp; tránh mặc định áp khung văn hoá phương Tây.
3. Mỗi luận điểm theo cấu trúc claim -> reasoning -> example -> impact, và KHÔNG trùng lặp ý. \
Trường "example" là 1 ví dụ đời thường, hoặc 1 tình huống giả định bắt đầu bằng "Giả sử...".
4. Luận điểm dự đoán của phe người học phải là luận điểm MẠNH NHẤT họ có thể đưa ra, không dựng "người rơm".
5. Mọi nội dung viết bằng tiếng Việt. Chỉ trả về JSON hợp lệ."""

    user_prompt = f"""KIẾN NGHỊ (MOTION): {motion}

PHE CỦA BẠN: {ai_side_label}
PHE NGƯỜI HỌC: {learner_side_label}

ĐỘ KHÓ: {_DIFFICULTY_GUIDE[difficulty]}
Số luận điểm của bạn: ĐÚNG {n_args} (id A1..A{n_args}). Số luận điểm dự đoán của phe người học: \
{n_args} (id O1..O{n_args}).

Trả về JSON đúng schema sau (giá trị trong <...> là mô tả, thay bằng nội dung thật; tên field giữ \
nguyên tiếng Anh; "definitions" có thể rỗng nếu kiến nghị không có thuật ngữ cần định nghĩa):
{json.dumps(_OUTPUT_EXAMPLE, ensure_ascii=False, indent=2)}"""
    return system_prompt, user_prompt
