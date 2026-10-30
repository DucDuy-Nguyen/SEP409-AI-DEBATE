"""
Prompt Case Planning v6 — THI NGHIEM motion_type (A/B voi v5, dev log muc 2.13). v5 GIU NGUYEN va van la mac dinh.

Chi dung khi session co CA motion_type va motion_reading (Main Flow gui, da duoc duyet). Bang v5, cong:
- Phan "tu dien giai" trong quy tac 1 cua v5 (SIDE_RULE) duoc THAY bang cach hieu co dinh
  (nguyen van spec): "Cách hiểu kiến nghị trong trận này (đã được ban tổ chức duyệt, dùng nguyên văn, không diễn giải
  lại): '{motion_reading}'."
- Nap DUNG 1 module theo loai kien nghi (nguyen van spec) — quy tac 2 moi.
- Mau JSON: motion_reading = chep nguyen van cach hieu tren. Code (service) GHI DE case_file.motion_reading bang ban
  duoc gui bat ke model tra gi, va log neu model tra khac.
Cac quy tac con lai (2..13 cua v5 -> 3..14), CaseFile, so luan diem, JSON schema: giong het v5. KHONG gop sua loi khac.
"""
import json

from app.opponent.models import DebateSide, MotionType, OpponentDifficulty
from app.opponent.prompts.case_plan_v3 import (  # noqa: F401 — build_response_schema dung chung
    _DIFFICULTY_GUIDE,
    _OUTPUT_EXAMPLE,
    ARGUMENT_COUNT_BY_DIFFICULTY,
    SIDE_LABEL,
    SIDE_RULE,
    build_response_schema,
)
from app.opponent.prompts.case_plan_v4 import MECHANISM_RULE
from app.opponent.prompts.case_plan_v5 import HYPOTHETICAL_NUMBER_RULE, NO_VAGUE_OBSERVATION_RULE

PROMPT_VERSION = "case_plan_v6"

# Nguyen van spec.
FIXED_READING_RULE = (
    "Cách hiểu kiến nghị trong trận này (đã được ban tổ chức duyệt, dùng nguyên văn, không diễn giải lại): "
    "'{motion_reading}'."
)
MOTION_TYPE_MODULE = {
    MotionType.POLICY: (
        "Đây là kiến nghị CHÍNH SÁCH. Phe Đề xuất phải nêu cơ chế thực hiện khả thi và lợi ích của nó; phe Phản "
        "đối có thể tấn công tính khả thi, tác dụng phụ, hoặc chỉ ra cách làm hiện tại tốt hơn. Mỗi phe có ít nhất một "
        "luận điểm về thực thi."
    ),
    MotionType.COMPARATIVE: (
        "Đây là kiến nghị SO SÁNH giữa hai lựa chọn. Phe của bạn phải vừa chỉ ra ưu điểm của lựa chọn mình bảo vệ, "
        "vừa chỉ ra nhược điểm của lựa chọn kia. Phần cân nhắc phải so sánh trực tiếp hai lựa chọn theo cùng tiêu chí."
    ),
    MotionType.VALUE: (
        "Đây là kiến nghị CÂN NHẮC/GIÁ TRỊ, không có chính sách cụ thể. Không cần cơ chế thực thi. Hãy nêu rõ tiêu chí "
        "cân nhắc (ai bị ảnh hưởng, mức độ, thời gian) và phần cân nhắc phải dựa trên tiêu chí đó."
    ),
}
# SIDE_RULE cua v5: phe Phan doi = TOAN BO la ve cach hieu kien nghi -> bo; phe De xuat = 1 cau cach hieu ("Định nghĩa
# kiến nghị một cách công bằng...") + 2 cau KHONG ve cach hieu (khong mo ta sai hien trang, khong neu chi tiet khong
# chac) -> GIU 2 cau sau de v6 chi khac v5 dung phan "tu dien giai".
_PRO_DEFINITION_SENTENCE = "Định nghĩa kiến nghị một cách công bằng và hợp lý, như cách một trọng tài trung lập sẽ hiểu. "
assert SIDE_RULE[DebateSide.PRO].startswith(_PRO_DEFINITION_SENTENCE)
SIDE_RULE_KEPT = {
    DebateSide.PRO: SIDE_RULE[DebateSide.PRO].removeprefix(_PRO_DEFINITION_SENTENCE),
    DebateSide.CON: "",
}
# Mau JSON: chi doi mo ta cua motion_reading (v5: "<cách bạn hiểu kiến nghị, phạm vi, giả định hợp lý>").
_OUTPUT_EXAMPLE_V6 = {**_OUTPUT_EXAMPLE, "motion_reading": "<chép NGUYÊN VĂN cách hiểu kiến nghị đã cho ở quy tắc 1>"}


def build_case_plan_prompt(
    motion: str,
    ai_side: DebateSide,
    learner_side: DebateSide,
    difficulty: OpponentDifficulty,
    motion_type: MotionType | None = None,
    motion_reading: str | None = None,
) -> tuple[str, str]:
    if motion_type is None or not motion_reading:
        raise ValueError("case_plan_v6 can motion_type va motion_reading")
    rule_1 = FIXED_READING_RULE.format(motion_reading=motion_reading)
    return build_prompt_with_rule_1(motion, ai_side, learner_side, difficulty, motion_type, rule_1, _OUTPUT_EXAMPLE_V6)


def build_prompt_with_rule_1(
    motion: str,
    ai_side: DebateSide,
    learner_side: DebateSide,
    difficulty: OpponentDifficulty,
    motion_type: MotionType,
    rule_1: str,
    output_example: dict,
) -> tuple[str, str]:
    """Khung prompt dung chung v6 / v6b: chi khac QUY TAC 1 (khoi cach hieu) va mo ta motion_reading trong mau JSON."""
    motion_type = MotionType(motion_type)
    ai_side_label = SIDE_LABEL[ai_side]
    learner_side_label = SIDE_LABEL[learner_side]
    n_args = ARGUMENT_COUNT_BY_DIFFICULTY[difficulty]

    system_prompt = f"""Bạn là một người tranh biện giàu kinh nghiệm, đóng vai ĐỐI THỦ của một người học \
trên nền tảng luyện tập tranh biện ADPP. Nhiệm vụ hiện tại: CHUẨN BỊ HỒ SƠ LẬP LUẬN \
trước khi trận đấu bắt đầu — chưa nói với người học, chỉ lập kế hoạch.

Bạn thuộc phe {ai_side_label}. Người học thuộc phe {learner_side_label}. Phe của bạn là CỐ ĐỊNH và không bao giờ thay đổi.

QUY TẮC BẮT BUỘC:
1. {rule_1}{(" " + SIDE_RULE_KEPT[ai_side]) if SIDE_RULE_KEPT[ai_side] else ""}
2. {MOTION_TYPE_MODULE[motion_type]}
3. KHÔNG bịa số liệu thống kê, tỷ lệ phần trăm, tên nghiên cứu, tên tổ chức hay trích dẫn cụ thể. Chỉ dùng lý lẽ logic, ví dụ đời thường, hoặc tình huống giả định được ghi rõ là giả định.
4. {MECHANISM_RULE}
5. Mọi ví dụ PHẢI bắt đầu bằng 'Giả sử'.
6. Impact phải tương xứng với reasoning; không khẳng định những hệ quả lớn (như giảm tỷ lệ trầm cảm, tự tử, thất nghiệp) nếu reasoning không trực tiếp chứng minh.
7. Ưu tiên bối cảnh Việt Nam (giáo dục, gia đình, xã hội Việt Nam) khi phù hợp; tránh mặc định áp khung văn hoá phương Tây.
8. Mỗi luận điểm theo cấu trúc claim -> reasoning -> example -> impact, và KHÔNG trùng lặp ý.
9. Luận điểm dự đoán của phe người học phải là luận điểm MẠNH NHẤT họ có thể đưa ra, không dựng "người rơm".
10. Chỉ dùng tiếng Việt, kể cả tên phe (Đề xuất / Phản đối).
11. Trước khi trả kết quả, kiểm tra: không lập luận nào tấn công hay dựa vào điều mà chính phần định nghĩa của bạn đã loại trừ.
12. {HYPOTHETICAL_NUMBER_RULE}
13. {NO_VAGUE_OBSERVATION_RULE}
14. Mọi nội dung viết bằng tiếng Việt. Chỉ trả về JSON hợp lệ."""

    user_prompt = f"""KIẾN NGHỊ: {motion}

PHE CỦA BẠN: {ai_side_label}
PHE NGƯỜI HỌC: {learner_side_label}

ĐỘ KHÓ: {_DIFFICULTY_GUIDE[difficulty]}
Số luận điểm của bạn: ĐÚNG {n_args} (id A1..A{n_args}). Số luận điểm dự đoán của phe người học: \
{n_args} (id O1..O{n_args}).

Trả về JSON đúng cấu trúc sau (giá trị trong <...> là mô tả, thay bằng nội dung thật; tên trường giữ \
nguyên như mẫu; "definitions" có thể rỗng nếu kiến nghị không có thuật ngữ cần định nghĩa):
{json.dumps(output_example, ensure_ascii=False, indent=2)}"""
    return system_prompt, user_prompt
