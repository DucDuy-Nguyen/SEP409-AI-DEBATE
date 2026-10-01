"""
Prompt Case Planning v3 (dang dung). v2 giu nguyen de doi chieu nhung KHONG con dung duoc voi
CaseFile hien tai (v2 sinh `opponent_claim`, gio da doi thanh `learner_claim`).

Thay doi so voi v2 (ly do: xem docs/AI_DEVELOPMENT_LOG.md muc 2.4d):
- Luat rieng theo phe: Đề xuất dinh nghia cong bang, khong mo ta sai hien trang;
  Phản đối chap nhan cach hieu pho bien, khong thu hep kien nghi.
- Tu kiem tra: lap luan khong duoc dua vao dieu phan dinh nghia da loai tru.
- Cam bang chung mo ho ("nghien cuu cho thay", ...).
- Moi vi du PHAI bat dau bang "Giả sử" (CaseFile validate, sai -> retry).
- Impact phai tuong xung voi reasoning.
- Chi tieng Viet, ke ca ten phe (bo "Proposition"/"Opposition", bo "MOTION" trong prompt).
- anticipated_opponent_arguments[].opponent_claim -> learner_claim.
- Kem JSON schema (structured output) theo do kho: so luan diem + pattern "Giả sử" duoc ep ngay
  khi sinh neu provider ho tro (hien tai: Groq).

Cac cau danh dau "nguyen van" trong spec duoc giu DUNG tung chu; tests kiem tra tung cau.
"""
import copy
import json

from app.opponent.models import DebateSide, OpponentDifficulty
from app.opponent.schemas import EXAMPLE_PREFIX, CaseFile

PROMPT_VERSION = "case_plan_v3"

# So luan diem BAT BUOC theo do kho — service va JSON schema dung chung hang so nay.
ARGUMENT_COUNT_BY_DIFFICULTY = {
    OpponentDifficulty.EASY: 2,
    OpponentDifficulty.MEDIUM: 3,
    OpponentDifficulty.HARD: 3,
}

SIDE_LABEL = {
    DebateSide.PRO: "Đề xuất",
    DebateSide.CON: "Phản đối",
}

# Nguyen van spec — chon theo phe cua AI.
SIDE_RULE = {
    DebateSide.PRO: (
        "Định nghĩa kiến nghị một cách công bằng và hợp lý, như cách một trọng tài trung lập sẽ hiểu. "
        "KHÔNG mô tả sai hiện trạng để làm lập luận của mình mạnh hơn. "
        "Nếu không chắc về một chi tiết thực tế, đừng nêu nó."
    ),
    DebateSide.CON: (
        "Chấp nhận cách hiểu phổ biến và hợp lý nhất của kiến nghị. "
        "KHÔNG thêm ngoại lệ hay điều kiện làm hẹp kiến nghị."
    ),
}

_DIFFICULTY_GUIDE = {
    OpponentDifficulty.EASY: (
        "DỄ: lập luận đơn giản, dễ hiểu; có thể còn 1 vài lỗ hổng nhỏ để người học (người mới) "
        "có cơ hội phản biện."
    ),
    OpponentDifficulty.MEDIUM: "TRUNG BÌNH: lập luận chặt chẽ ở mức khá, có cơ chế rõ ràng.",
    OpponentDifficulty.HARD: (
        "KHÓ: các luận điểm mạnh nhất có thể, cơ chế chặt chẽ, phần cân nhắc tổng thể sắc bén, "
        "chủ động chặn trước các phản biện phổ biến."
    ),
}

_OUTPUT_EXAMPLE = {
    # Doi tu "motion_interpretation" (2026-09-29, migration 0007) — ap dung cho v3 / v4 / v5 vi dung chung
    # CaseFile; ngoai ten truong, noi dung prompt v3 / v4 KHONG doi.
    "motion_reading": "<cách bạn hiểu kiến nghị, phạm vi, giả định hợp lý>",
    "definitions": [{"term": "<thuật ngữ trong kiến nghị>", "meaning": "<định nghĩa bạn dùng>"}],
    "arguments": [
        {
            "id": "A1",
            "title": "<tên ngắn của luận điểm>",
            "claim": "<khẳng định chính>",
            "reasoning": "<cơ chế / chuỗi suy luận vì sao khẳng định đúng>",
            "example": "Giả sử <tình huống cụ thể minh hoạ cho cơ chế>",
            "impact": "<hệ quả, tương xứng với những gì reasoning đã chứng minh>",
        }
    ],
    "anticipated_opponent_arguments": [
        {
            "id": "O1",
            "learner_claim": "<luận điểm mạnh nhất phe người học có thể đưa ra>",
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

    system_prompt = f"""Bạn là một người tranh biện giàu kinh nghiệm, đóng vai ĐỐI THỦ của một người học \
trên nền tảng luyện tập tranh biện ADPP. Nhiệm vụ hiện tại: CHUẨN BỊ HỒ SƠ LẬP LUẬN \
trước khi trận đấu bắt đầu — chưa nói với người học, chỉ lập kế hoạch.

Bạn thuộc phe {ai_side_label}. Người học thuộc phe {learner_side_label}. Phe của bạn là CỐ ĐỊNH và không bao giờ thay đổi.

QUY TẮC BẮT BUỘC:
1. {SIDE_RULE[ai_side]}
2. KHÔNG bịa số liệu thống kê, tỷ lệ phần trăm, tên nghiên cứu, tên tổ chức hay trích dẫn cụ thể. Chỉ dùng lý lẽ logic, ví dụ đời thường, hoặc tình huống giả định được ghi rõ là giả định.
3. KHÔNG viện dẫn bằng chứng mơ hồ như 'nghiên cứu cho thấy', 'nhiều quốc gia đã áp dụng thành công', 'đã được chứng minh', 'các chuyên gia cho rằng'.
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


def build_response_schema(difficulty: OpponentDifficulty) -> dict:
    """
    JSON schema cho structured output (strict), sinh TU CaseFile de khong lech voi validator:
    moi object additionalProperties=false + moi truong required (yeu cau cua strict mode),
    so luan diem dung theo do kho, example khop pattern "^Giả sử".
    Validator Pydantic van chay sau do — schema chi la lop chan som, khong thay the validation.
    """
    schema = copy.deepcopy(CaseFile.model_json_schema())

    def strictify(node: object) -> None:
        if isinstance(node, list):
            for item in node:
                strictify(item)
            return
        if not isinstance(node, dict):
            return
        node.pop("title", None)  # metadata cua pydantic, khong phai ten field
        node.pop("default", None)
        props = node.get("properties")
        if isinstance(props, dict):
            node["additionalProperties"] = False
            node["required"] = list(props)
            for field_schema in props.values():
                strictify(field_schema)
        for key, value in node.items():
            if key != "properties":
                strictify(value)

    strictify(schema)
    n_args = ARGUMENT_COUNT_BY_DIFFICULTY[difficulty]
    schema["properties"]["arguments"]["minItems"] = n_args
    schema["properties"]["arguments"]["maxItems"] = n_args
    schema["$defs"]["CaseArgument"]["properties"]["example"]["pattern"] = f"^{EXAMPLE_PREFIX}"
    return schema
