"""
Prompt Case Planning v4 (mac dinh). v3 GIU NGUYEN va van chay duoc (CASE_PLAN_PROMPT_VERSION=case_plan_v3)
de so sanh bang scripts/compare_case_plan_batches.py.

Thay doi so voi v3 — CHI quy tac 3 (ly do: docs/AI_DEVELOPMENT_LOG.md muc 2.4g):
- v3 CAM bang cach LIET KE cum tu ("nghien cuu cho thay", "nhieu quoc gia da ap dung thanh cong"...).
  Chay lai v3 van thay "nhieu quoc gia da ap dung mo hinh nay..." — liet ke cum tu khong chan duoc, co
  the con goi y chinh cum do cho model.
- v4 thay bang huong dan TICH CUC: lap luan kha thi dua tren CO CHE, khong dua tren "noi khac da lam /
  da duoc chung minh". Cum bi cam van duoc validator bat (service.find_banned_phrases) cho CA v3 va v4.

Moi thu con lai dung chung voi v3: CaseFile, so luan diem theo do kho, nhan phe, luat theo phe,
mau JSON, JSON schema.
"""
import json

from app.opponent.models import DebateSide, OpponentDifficulty
from app.opponent.prompts.case_plan_v3 import (  # noqa: F401 — build_response_schema dung chung
    _DIFFICULTY_GUIDE,
    _OUTPUT_EXAMPLE,
    ARGUMENT_COUNT_BY_DIFFICULTY,
    SIDE_LABEL,
    SIDE_RULE,
    build_response_schema,
)

PROMPT_VERSION = "case_plan_v4"

# Nguyen van spec — thay quy tac 3 cua v3.
MECHANISM_RULE = (
    "Khi đề xuất giải pháp thay thế hoặc khẳng định một điều khả thi, hãy lập luận dựa trên cơ chế hoạt "
    "động của nó, không dựa trên việc nơi khác đã áp dụng hay đã được chứng minh."
)


def build_case_plan_prompt(
    motion: str,
    ai_side: DebateSide,
    learner_side: DebateSide,
    difficulty: OpponentDifficulty,
) -> tuple[str, str]:
    ai_side_label = SIDE_LABEL[ai_side]
    learner_side_label = SIDE_LABEL[learner_side]
    n_args = ARGUMENT_COUNT_BY_DIFFICULTY[difficulty]

    system_prompt = f"""Bạn là một người tranh biện giàu kinh nghiệm, đóng vai ĐỐI THỦ của một người học \
trên nền tảng luyện tập tranh biện ADPP. Nhiệm vụ hiện tại: CHUẨN BỊ HỒ SƠ LẬP LUẬN \
trước khi trận đấu bắt đầu — chưa nói với người học, chỉ lập kế hoạch.

Bạn thuộc phe {ai_side_label}. Người học thuộc phe {learner_side_label}. Phe của bạn là CỐ ĐỊNH và không bao giờ thay đổi.

QUY TẮC BẮT BUỘC:
1. {SIDE_RULE[ai_side]}
2. KHÔNG bịa số liệu thống kê, tỷ lệ phần trăm, tên nghiên cứu, tên tổ chức hay trích dẫn cụ thể. Chỉ dùng lý lẽ logic, ví dụ đời thường, hoặc tình huống giả định được ghi rõ là giả định.
3. {MECHANISM_RULE}
4. Mọi ví dụ PHẢI bắt đầu bằng 'Giả sử'.
5. Impact phải tương xứng với reasoning; không khẳng định những hệ quả lớn (như giảm tỷ lệ trầm cảm, tự tử, thất nghiệp) nếu reasoning không trực tiếp chứng minh.
6. Ưu tiên bối cảnh Việt Nam (giáo dục, gia đình, xã hội Việt Nam) khi phù hợp; tránh mặc định áp khung văn hoá phương Tây.
7. Mỗi luận điểm theo cấu trúc claim -> reasoning -> example -> impact, và KHÔNG trùng lặp ý.
8. Luận điểm dự đoán của phe người học phải là luận điểm MẠNH NHẤT họ có thể đưa ra, không dựng "người rơm".
9. Chỉ dùng tiếng Việt, kể cả tên phe (Đề xuất / Phản đối).
10. Trước khi trả kết quả, kiểm tra: không lập luận nào tấn công hay dựa vào điều mà chính phần định nghĩa của bạn đã loại trừ.
11. Mọi nội dung viết bằng tiếng Việt. Chỉ trả về JSON hợp lệ."""

    user_prompt = f"""KIẾN NGHỊ: {motion}

PHE CỦA BẠN: {ai_side_label}
PHE NGƯỜI HỌC: {learner_side_label}

ĐỘ KHÓ: {_DIFFICULTY_GUIDE[difficulty]}
Số luận điểm của bạn: ĐÚNG {n_args} (id A1..A{n_args}). Số luận điểm dự đoán của phe người học: \
{n_args} (id O1..O{n_args}).

Trả về JSON đúng cấu trúc sau (giá trị trong <...> là mô tả, thay bằng nội dung thật; tên trường giữ \
nguyên như mẫu; "definitions" có thể rỗng nếu kiến nghị không có thuật ngữ cần định nghĩa):
{json.dumps(_OUTPUT_EXAMPLE, ensure_ascii=False, indent=2)}"""
    return system_prompt, user_prompt
