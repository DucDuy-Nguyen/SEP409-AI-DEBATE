"""
Prompt Case Planning v5 (mac dinh tu 2026-09-29). v3 va v4 GIU NGUYEN va van chay duoc (CASE_PLAN_PROMPT_VERSION).

Thay doi so voi v4 — THEM 2 quy tac (nguyen van spec), ly do: docs/AI_DEVELOPMENT_LOG.md muc 2.4j:
- 11. So trong tinh huong gia dinh: nhan tay batch v3/v4 cho thay vi du "Giả sử" hay gan so voi dia danh / co quan /
  thiet bi co that ("Giả sử ở Hà Nội ... 30% là xe máy", "trạm quan trắc ...") — doc nhu so lieu that du da danh
  dau gia dinh.
- 12. Khang dinh "da xay ra" voi chu the chung chung: vd v4 M05 pro hard "nhiều sinh viên đã chứng minh khả năng duy
  trì thành tích học tập tốt đồng thời làm thêm" — lot validator cu, la bang chung mo ho doi lot "quan sat thuc te".
Quy tac "Chi tra ve JSON hop le" van o cuoi (thanh 13).

Moi thu con lai dung chung voi v3 / v4: CaseFile, so luan diem, nhan phe, luat theo phe, quy tac co che (v4), mau JSON,
JSON schema.
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
from app.opponent.prompts.case_plan_v4 import MECHANISM_RULE

PROMPT_VERSION = "case_plan_v5"

# Nguyen van spec.
HYPOTHETICAL_NUMBER_RULE = (
    "Con số trong tình huống giả định phải hợp lý về độ lớn và KHÔNG được gắn với địa điểm, tổ chức, cơ quan hay "
    "thiết bị đo lường có thật (ví dụ tên thành phố cụ thể, trạm quan trắc)."
)
NO_VAGUE_OBSERVATION_RULE = (
    "Không khẳng định rằng một điều đã xảy ra hay đã được quan sát ngoài đời thật với chủ thể chung chung như "
    "'nhiều sinh viên', 'nhiều nơi', 'một số nước'."
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
11. {HYPOTHETICAL_NUMBER_RULE}
12. {NO_VAGUE_OBSERVATION_RULE}
13. Mọi nội dung viết bằng tiếng Việt. Chỉ trả về JSON hợp lệ."""

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
