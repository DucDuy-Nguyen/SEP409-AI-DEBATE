"""
Bo do bang chung mo ho moi (app/opponent/vague_detector.py): quy tac HIGH / LOW, pham vi truong, validator.
Cau "tap thiet ke" lay NGUYEN VAN tu nhan batch v3 (experiments/labels/vague_evidence_labels.csv, 20260927-092737).
"""
import copy
import json

import pytest

from app.core.config import Settings
from app.opponent import vague_detector as vd
from app.opponent.models import DebateSide, OpponentDifficulty
from app.opponent.service import FailureKind, detect_vague_evidence, generate_case_file
from tests.conftest import VALID_CASE_FILE, FakeLLMClient


def _case_with(path: tuple, text: str) -> dict:
    data = copy.deepcopy(VALID_CASE_FILE)
    node = data
    for part in path[:-1]:
        node = node[part]
    node[path[-1]] = text
    return data


def _levels(path: tuple, text: str) -> list[tuple[str, str]]:
    field = "".join(f"[{p}]" if isinstance(p, int) else (f".{p}" if i else p) for i, p in enumerate(path))
    return [(h.level, h.rule) for h in vd.detect(_case_with(path, text)) if h.field == field]


# ---------------- tap thiet ke v3: 13 nhan tay (1 'a', 12 'n') ----------------

DESIGN_SET = [
    # (nhan, duong dan truong, cau nguyen van, muc ky vong: "high" | "low" | None)
    ("n", ("arguments", 0, "impact"),
     "Kết quả là giảm công bằng trong tuyển sinh, học sinh có năng lực nhưng không có cơ hội chứng minh qua tiêu chuẩn chung sẽ bị thiệt thòi.", None),
    ("a", ("anticipated_opponent_arguments", 0, "planned_response"),
     "thực tế, kỹ năng quản lý thời gian được cải thiện qua việc làm, và một số nghiên cứu (không nêu cụ thể) cho thấy sinh viên làm thêm không có xu hướng điểm số giảm nếu thời gian làm việc được giới hạn hợp lý.", "high"),
    ("n", ("arguments", 0, "reasoning"),
     "Khi phải làm việc thêm, sinh viên phải dành phần lớn thời gian cho việc đi lại, làm việc và nghỉ ngơi, do đó thời gian dành cho đọc sách, làm bài tập, tham gia các buổi học bổ trợ và nghiên cứu giảm đi đáng kể, dẫn đến khả năng nắm bắt kiến thức kém hơn.", "low"),
    ("n", ("anticipated_opponent_arguments", 1, "planned_response"),
     "Chúng tôi sẽ chỉ ra rằng kinh nghiệm thực tiễn có thể được tích lũy thông qua các chương trình thực tập, dự án nghiên cứu, hoặc hoạt động ngoại khóa được thiết kế đặc thù cho sinh viên, mà không cần phải hi sinh thời gian học tập và sức khỏe.", "low"),
    ("n", ("anticipated_opponent_arguments", 1, "planned_response"), "thí điểm có thể chứng minh tính khả thi.", None),
    ("n", ("arguments", 0, "example"), "Giả sử ở Hà Nội, trong giờ cao điểm các con đường chính có khoảng 30% là xe máy.", None),
    ("n", ("arguments", 2, "example"),
     "Giả sử cơ quan quản lý thành phố triển khai lệnh cấm, nhưng 70% xe máy vẫn lưu thông vào ban đêm mà không có giấy tờ, gây ra tai nạn và khó kiểm soát.", None),
    ("n", ("arguments", 1, "reasoning"),
     "Các thành phố lớn có các trường đại học, trung tâm nghiên cứu, vườn ươm khởi nghiệp và các sự kiện kết nối doanh nghiệp, tạo ra môi trường tương tác và chia sẻ kiến thức nhanh chóng.", "low"),
    ("n", ("arguments", 1, "example"),
     "Giả sử sau khi thuế tăng, các quán vỉa hè ở Hà Nội bắt đầu bán nước ngọt tự pha với giá 20 % rẻ hơn so với sản phẩm đóng gói, không qua kiểm soát chất lượng.", None),
]


@pytest.mark.parametrize("label,path,sentence,expected", DESIGN_SET)
def test_design_set_v3(label, path, sentence, expected):
    levels = {lvl for lvl, _ in _levels(path, sentence)}
    if expected is None:
        assert levels == set(), levels
    else:
        assert expected in levels and (expected == "high" or "high" not in levels)
    # khong co hit HIGH nao tren cau nhan 'n' (muc tieu thiet ke: 0 bat nham o muc reject)
    if label == "n":
        assert "high" not in levels


# ---------------- tung quy tac HIGH ----------------

W = ("weighing",)


@pytest.mark.parametrize(
    "sentence,rule",
    [
        ("Nghiên cứu cho thấy học sinh ngủ ít hơn.", "nghien_cuu_ket_luan"),
        ("Một nghiên cứu gần đây đã chỉ ra điều ngược lại.", "nghien_cuu_ket_luan"),
        ("Các chuyên gia cho rằng đây là cách tốt nhất.", "chuyen_gia_nhan_dinh"),
        ("Nhiều chuyên gia y tế khuyến cáo nên giảm đường.", "chuyen_gia_nhan_dinh"),
        ("Các giải pháp thay thế đã được chứng minh khả thi.", "nhieu_chu_the_da"),  # cau that mau v2 so 2
        ("Hiệu quả của mô hình này đã được chứng minh.", "da_chung_minh"),
        ("Nhiều sinh viên đã chứng minh khả năng duy trì thành tích học tập tốt đồng thời làm thêm.", "nhieu_chu_the_da"),
        ("Nhiều quốc gia đã áp dụng thành công chính sách này.", "nhieu_chu_the_da"),
        ("Nhiều quốc gia đã áp dụng mô hình này mà vẫn duy trì tiêu chuẩn tuyển sinh cao.", "nhieu_noi_da_ap_dung"),
        ("Một số trường đã cho thấy kết quả tốt.", "nhieu_chu_the_da"),
    ],
)
def test_high_rules(sentence, rule):
    assert ("high", rule) in _levels(W, sentence)


@pytest.mark.parametrize(
    "sentence",
    [
        "Phe phản đối thắng khi chứng minh rằng thiệt hại lớn hơn.",  # khong co "đã"
        "Như chúng tôi đã chứng minh ở luận điểm A1, chi phí sẽ tăng.",  # chu the = chung toi
        "Phe đề xuất đã chứng minh được lợi ích lâu dài.",  # chu the = phe
        "Đội bạn đã được chứng minh là sai ở điểm này.",  # chu the = doi
        "Chuyên gia tài chính là nghề được trả lương cao.",  # chuyen gia, khong dong tu nhan dinh
        "Nghiên cứu sinh cần nhiều thời gian đọc tài liệu. Kết quả cho thấy điều gì?",  # khac cau
    ],
)
def test_not_high(sentence):
    assert "high" not in {lvl for lvl, _ in _levels(W, sentence)}


def test_verb_must_be_within_six_words_of_nghien_cuu():
    near = "Một số nghiên cứu (không nêu cụ thể) cho thấy điều đó."
    far = "Nghiên cứu về thói quen ăn uống của thanh thiếu niên ở nhiều vùng miền khác nhau cho thấy điều đó."
    assert ("high", "nghien_cuu_ket_luan") in _levels(W, near)
    assert ("high", "nghien_cuu_ket_luan") not in _levels(W, far)


# ---------------- pham vi truong ----------------


def test_no_number_scan_in_example_and_definitions():
    assert _levels(("arguments", 0, "example"), "Giả sử giá tăng 30%.") == []
    assert _levels(("definitions", 0, "meaning"), "Mức thuế trên 20%.") == []
    assert _levels(("arguments", 0, "reasoning"), "Giá tăng 30% thì cầu giảm.") == [("low", "phan_tram")]


def test_learner_claim_high_is_downgraded_to_low():
    # Cau THAT (M10 con medium, batch v3 17:14): learner viện dẫn "nhiều quốc gia đã áp dụng" la du doan hop le.
    sentence = ("Nhiều quốc gia đã áp dụng thuế cao đối với đồ uống có đường và đạt được thành công trong việc "
                "cải thiện sức khỏe cộng đồng.")
    levels = _levels(("anticipated_opponent_arguments", 0, "learner_claim"), sentence)
    assert levels and all(lvl == "low" for lvl, _ in levels)


@pytest.mark.parametrize(
    "path",
    [("motion_reading",), ("definitions", 0, "term"), ("arguments", 1, "title"), ("arguments", 2, "claim"),
     ("arguments", 0, "reasoning"), ("arguments", 0, "impact"), ("arguments", 0, "example"),
     ("anticipated_opponent_arguments", 1, "planned_response"), ("weighing",)],
)
def test_high_applies_to_all_ai_fields(path):
    text = "Giả sử các chuyên gia cho rằng như vậy." if path[-1] == "example" else "Các chuyên gia cho rằng như vậy."
    assert ("high", "chuyen_gia_nhan_dinh") in _levels(path, text)


def test_old_field_name_still_scanned_as_ai_field():
    assert vd.field_scope("motion_interpretation") == "ai" and vd.field_scope("motion_reading") == "ai"


def test_one_hit_per_span_high_wins():
    hits = vd.detect(_case_with(W, "Các chuyên gia cho rằng nghiên cứu cho thấy 30% học sinh ngủ ít."))
    assert [(h.level, h.rule) for h in hits if h.field == "weighing"] == [
        ("high", "nghien_cuu_ket_luan"), ("high", "chuyen_gia_nhan_dinh"), ("low", "phan_tram"),
    ]


def test_log_format():
    [entry] = detect_vague_evidence(_case_with(W, "Theo thống kê thì khác."))
    assert entry == {"phrase": "thống kê / theo báo cáo", "field": "weighing", "level": "low", "rule": "thong_ke",
                     "match": "thống kê"}


# ---------------- validator: HIGH reject (retry co phan hoi), LOW chi log ----------------


async def _run(responses):
    fake = FakeLLMClient(list(responses))
    outcome = await generate_case_file(
        "M", DebateSide.CON, DebateSide.PRO, OpponentDifficulty.MEDIUM, fake, Settings(_env_file=None)
    )
    return outcome, fake


async def test_high_is_rejected_with_feedback():
    bad = json.dumps(_case_with(("arguments", 1, "reasoning"), "Nhiều sinh viên đã chứng minh điều này."), ensure_ascii=False)
    outcome, fake = await _run([bad, json.dumps(VALID_CASE_FILE)])

    failed = outcome.attempts[0]
    assert failed.failure_kind == FailureKind.BANNED_PHRASE
    assert "`arguments[1].reasoning` có lời viện dẫn bằng chứng mơ hồ \"Nhiều sinh viên đã chứng minh\"" in failed.retry_feedback
    assert outcome.case_file is not None and len(fake.calls) == 2


async def test_low_is_only_logged():
    text = "Theo thống kê, 70% học sinh thiếu ngủ; các trung tâm nghiên cứu cũng quan tâm."
    ok = json.dumps(_case_with(("arguments", 0, "reasoning"), text), ensure_ascii=False)
    outcome, fake = await _run([ok])

    assert outcome.case_file is not None and len(fake.calls) == 1
    assert {e["rule"] for e in outcome.attempts[0].vague_evidence} == {"thong_ke", "phan_tram", "nghien_cuu"}
    assert all(e["level"] == "low" for e in outcome.attempts[0].vague_evidence)
