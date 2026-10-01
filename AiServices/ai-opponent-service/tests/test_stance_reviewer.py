"""
Stance Reviewer: phan loai phe (LLM gia lap) + ket luan bang code + tich hop vao Case Planning.
"""
import inspect
import json

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.opponent import stance_reviewer as sr
from app.opponent.models import DebateSide, LLMCallPurpose, OpponentDifficulty, ReviewerVerdict
from app.opponent.schemas import CaseFile
from app.opponent.service import generate_case_file
from tests.conftest import VALID_CASE_FILE, FakeLLMClient, FakeStanceReviewer

PRO, CON = DebateSide.PRO, DebateSide.CON
UNG_HO, PHAN_DOI, KHONG_RO = "ung_ho_kien_nghi", "phan_doi_kien_nghi", "khong_ro"
MOTION = "Học sinh không nên có bài tập về nhà"


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def _review(positions: dict[str, str], weighing: str) -> sr.StanceReviewOutput:
    return sr.StanceReviewOutput.model_validate(
        {
            "arguments": [{"id": i, "position": p, "reason": "r"} for i, p in positions.items()],
            "weighing": {"position": weighing, "reason": "r"},
        }
    )


# ---------------- judge(): ket luan bang code ----------------


@pytest.mark.parametrize(
    "ai_side,positions,weighing,expected,flipped,unclear",
    [
        (PRO, {"A1": UNG_HO, "A2": UNG_HO}, UNG_HO, ReviewerVerdict.PASS, [], []),
        (CON, {"A1": PHAN_DOI, "A2": PHAN_DOI}, PHAN_DOI, ReviewerVerdict.PASS, [], []),
        (PRO, {"A1": UNG_HO, "A2": PHAN_DOI}, UNG_HO, ReviewerVerdict.SIDE_FLIP, ["A2"], []),
        (CON, {"A1": PHAN_DOI, "A2": PHAN_DOI}, UNG_HO, ReviewerVerdict.SIDE_FLIP, ["weighing"], []),
        (CON, {"A1": KHONG_RO, "A2": PHAN_DOI}, PHAN_DOI, ReviewerVerdict.UNCLEAR, [], ["A1"]),
        # nguoc phe + khong ro -> side_flip thang
        (PRO, {"A1": KHONG_RO, "A2": PHAN_DOI}, UNG_HO, ReviewerVerdict.SIDE_FLIP, ["A2"], ["A1"]),
    ],
)
def test_judge(ai_side, positions, weighing, expected, flipped, unclear):
    verdict, detail = sr.judge(_review(positions, weighing), ai_side)
    assert verdict == expected
    assert detail["flipped_ids"] == flipped and detail["unclear_ids"] == unclear
    assert detail["expected_position"] == (UNG_HO if ai_side == PRO else PHAN_DOI)
    assert len(detail["positions"]) == len(positions) + 1  # + weighing


# ---------------- prompt: trong tai trung lap, KHONG biet phe ----------------


def test_review_prompt_has_no_side_parameter():
    assert list(inspect.signature(sr.build_review_prompt).parameters) == ["motion", "statements", "summary"]


def test_review_prompt_is_neutral_third_person():
    statements = [sr.Statement("A1", "Bài tập về nhà gây mất ngủ."), sr.Statement("A2", "Trẻ cần thời gian chơi.")]
    system, user = sr.build_review_prompt(MOTION, statements, "Tác hại lớn hơn lợi ích.")
    assert "TRỌNG TÀI TRUNG LẬP" in system and "KHÔNG phải người tranh biện" in system
    assert f"Một đội tranh luận đưa ra các luận điểm sau về kiến nghị '{MOTION}'" in user
    assert '- [A1] "Bài tập về nhà gây mất ngủ."' in user and "Tác hại lớn hơn lợi ích." in user
    for leak in ("Đề xuất", "Phản đối", "phe của bạn", "Bạn thuộc phe", "Proposition", "Opposition"):
        assert leak not in system + user, leak


def test_review_schema_is_strict():
    schema = sr.build_review_schema(["A1", "A2", "A3"], has_summary=True)
    args = schema["properties"]["arguments"]
    assert args["minItems"] == args["maxItems"] == 3
    assert args["items"]["properties"]["id"]["enum"] == ["A1", "A2", "A3"]
    assert args["items"]["properties"]["position"]["enum"] == [UNG_HO, PHAN_DOI, KHONG_RO]
    assert schema["required"] == ["arguments", "weighing"]
    assert schema["additionalProperties"] is False


def test_parse_review_requires_exact_ids_and_weighing():
    ok = json.dumps({"arguments": [{"id": "A1", "position": UNG_HO, "reason": "r"}], "weighing": {"position": UNG_HO, "reason": "r"}})
    assert sr.parse_review(ok, ["A1"], has_summary=True).arguments[0].id == "A1"
    with pytest.raises(ValueError, match="id"):
        sr.parse_review(ok, ["A1", "A2"], has_summary=True)  # thieu A2
    no_weighing = json.dumps({"arguments": [{"id": "A1", "position": UNG_HO, "reason": "r"}]})
    with pytest.raises(ValueError, match="weighing"):
        sr.parse_review(no_weighing, ["A1"], has_summary=True)
    bad_position = ok.replace(UNG_HO, "ung_ho", 1)
    with pytest.raises(ValidationError):
        sr.parse_review(bad_position, ["A1"], has_summary=True)


# ---------------- tich hop voi Case Planning (generate_case_file) ----------------


async def _plan(fake: FakeLLMClient, reviewer: FakeStanceReviewer, ai_side=CON, **settings):
    learner = PRO if ai_side == CON else CON
    return await generate_case_file(
        MOTION, ai_side, learner, OpponentDifficulty.MEDIUM, fake, _settings(**settings), reviewer
    )


async def test_side_flip_is_caught_and_retried():
    fake = FakeLLMClient([json.dumps(VALID_CASE_FILE), json.dumps(VALID_CASE_FILE)])
    reviewer = FakeStanceReviewer(PHAN_DOI)
    reviewer.responses = [  # lan 1: A2 ung ho kien nghi trong khi AI la phe Phan doi (dinh dang v1)
        json.dumps(
            {
                "arguments": [
                    {"id": "A1", "position": PHAN_DOI, "reason": "r"},
                    {"id": "A2", "position": UNG_HO, "reason": "lat phe"},
                    {"id": "A3", "position": PHAN_DOI, "reason": "r"},
                ],
                "weighing": {"position": PHAN_DOI, "reason": "r"},
            }
        )
    ]

    outcome = await _plan(fake, reviewer)

    assert outcome.case_file is not None and outcome.llm_error is None
    purposes = [a.purpose for a in outcome.attempts]
    assert purposes == [LLMCallPurpose.CASE_PLAN, LLMCallPurpose.STANCE_REVIEW] * 2
    first_plan, first_review, second_plan, second_review = outcome.attempts
    assert first_plan.success is False and first_plan.error.startswith("side_flip")
    assert first_plan.reviewer_verdict == ReviewerVerdict.SIDE_FLIP
    assert first_plan.reviewer_detail["flipped_ids"] == ["A2"]
    assert first_review.reviewer_verdict == ReviewerVerdict.SIDE_FLIP and first_review.success
    assert second_plan.success and second_plan.reviewer_verdict == ReviewerVerdict.PASS
    # retry trung tinh (muc 2.4m): lan 2 dung NGUYEN prompt goc, khong noi generator "da lat phe"
    assert fake.calls[1]["user"] == fake.calls[0]["user"]
    assert first_plan.retry_feedback is None
    assert first_plan.reviewer_detail["retry"] == "side_flip_neutral_retry"
    # [attempt] tang lien tuc qua ca planner + reviewer
    assert [a.attempt for a in outcome.attempts] == [1, 2, 3, 4]


async def test_side_flip_every_time_counts_as_invalid_output():
    fake = FakeLLMClient([json.dumps(VALID_CASE_FILE)] * 2)
    reviewer = FakeStanceReviewer(UNG_HO)  # moi muc deu ung ho -> nguoc phe con

    outcome = await _plan(fake, reviewer, case_plan_max_attempts=2)

    assert outcome.case_file is None and outcome.llm_error is None  # -> CasePlanningError (502), khong phai loi LLM
    plans = [a for a in outcome.attempts if a.purpose == LLMCallPurpose.CASE_PLAN]
    assert len(plans) == 2 and all(a.reviewer_verdict == ReviewerVerdict.SIDE_FLIP for a in plans)


async def test_khong_ro_is_not_rejected():
    fake = FakeLLMClient([json.dumps(VALID_CASE_FILE)])
    reviewer = FakeStanceReviewer(PHAN_DOI)
    reviewer.positions = {"A3": KHONG_RO}

    outcome = await _plan(fake, reviewer)

    assert outcome.case_file is not None
    plan = outcome.attempts[0]
    assert plan.success and plan.error is None
    assert plan.reviewer_verdict == ReviewerVerdict.UNCLEAR
    assert plan.reviewer_detail["unclear_ids"] == ["A3"]
    assert len(fake.calls) == 1  # khong retry


@pytest.mark.parametrize("failure", [RuntimeError("503 groq down"), "khong phai json"])
async def test_reviewer_failing_twice_is_unclear_not_blocking(failure):
    fake = FakeLLMClient([json.dumps(VALID_CASE_FILE)])
    reviewer = FakeStanceReviewer()
    reviewer.responses = [failure, failure]

    outcome = await _plan(fake, reviewer)

    assert outcome.case_file is not None and outcome.llm_error is None
    plan, review1, review2 = outcome.attempts  # CA 2 lan goi reviewer deu duoc log
    assert [review1.purpose, review2.purpose] == [LLMCallPurpose.STANCE_REVIEW] * 2
    assert review1.success is False and review2.success is False
    assert plan.reviewer_verdict == ReviewerVerdict.UNCLEAR and "reviewer_error" in plan.reviewer_detail
    assert plan.reviewer_detail["reviewer_calls"] == 2
    assert len(reviewer.calls) == 2


@pytest.mark.parametrize("failure", [RuntimeError("503 groq down"), "khong phai json"])
async def test_reviewer_retried_once_then_passes(failure):
    fake = FakeLLMClient([json.dumps(VALID_CASE_FILE)])
    reviewer = FakeStanceReviewer(PHAN_DOI)
    reviewer.responses = [failure]  # lan 2 tra review hop le (dung phe)

    outcome = await _plan(fake, reviewer, case_plan_max_attempts=1)

    # retry reviewer KHONG tinh vao so lan thu Case Planning: max_attempts=1 van thanh cong
    assert outcome.case_file is not None
    plan, failed_review, ok_review = outcome.attempts
    assert failed_review.success is False and ok_review.success is True
    assert plan.reviewer_verdict == ReviewerVerdict.PASS and plan.reviewer_detail["reviewer_calls"] == 2
    assert len(fake.calls) == 1 and len(reviewer.calls) == 2


async def test_reviewer_side_flip_is_not_retried_as_reviewer_error():
    # side_flip la ket luan hop le cua reviewer -> KHONG goi lai reviewer, ma retry Case Planning.
    fake = FakeLLMClient([json.dumps(VALID_CASE_FILE)] * 2)
    reviewer = FakeStanceReviewer(UNG_HO)

    await _plan(fake, reviewer, case_plan_max_attempts=2)

    assert len(reviewer.calls) == 2 and len(fake.calls) == 2  # 1 review / 1 case plan


@pytest.mark.parametrize("version", ["stance_review_v1", "stance_review_v2", "stance_review_v3"])
async def test_reviewer_never_receives_ai_side(version):
    reviewer_pro, reviewer_con = FakeStanceReviewer(UNG_HO), FakeStanceReviewer(PHAN_DOI)
    await _plan(FakeLLMClient([json.dumps(VALID_CASE_FILE)]), reviewer_pro, ai_side=PRO, stance_review_prompt_version=version)
    await _plan(FakeLLMClient([json.dumps(VALID_CASE_FILE)]), reviewer_con, ai_side=CON, stance_review_prompt_version=version)

    # Cung case file, khac phe -> reviewer nhan prompt GIONG HET nhau: khong co thong tin phe nao lot vao.
    assert reviewer_pro.calls[0]["system"] == reviewer_con.calls[0]["system"]
    assert reviewer_pro.calls[0]["user"] == reviewer_con.calls[0]["user"]
    user = reviewer_con.calls[0]["user"]
    # v1: motion + claim + weighing; v2 / v3: them REASONING. Khong bao gio co example / impact / learner_claim.
    case_file = CaseFile.model_validate(VALID_CASE_FILE)
    for a in case_file.arguments:
        assert a.claim in user and a.example not in user and a.impact not in user
        assert (a.reasoning in user) is (version != "stance_review_v1")
    assert case_file.weighing in user
    assert case_file.anticipated_opponent_arguments[0].learner_claim not in user


async def test_reviewer_uses_temperature_zero_schema_and_own_metadata():
    fake = FakeLLMClient([json.dumps(VALID_CASE_FILE)])
    reviewer = FakeStanceReviewer()

    outcome = await _plan(fake, reviewer)

    assert reviewer.calls[0]["temperature"] == 0.0
    assert reviewer.calls[0]["json_schema"] == sr.build_review_schema(["A1", "A2", "A3"], has_summary=True)
    review = outcome.attempts[1]
    assert (review.llm_model, review.prompt_version, review.temperature) == ("fake-reviewer", "stance_review_v1", 0.0)
    assert outcome.reviewer_model == "fake-reviewer"


async def test_reviewer_call_is_inside_total_budget():
    fake = FakeLLMClient([json.dumps(VALID_CASE_FILE)])
    reviewer = FakeStanceReviewer()
    reviewer.delay_seconds = 1.0

    outcome = await _plan(fake, reviewer, case_plan_total_budget_seconds=0.3)

    assert outcome.budget_exceeded and outcome.case_file is None
    plan, cut = outcome.attempts
    assert plan.error.startswith("budget_exceeded") and "stance review" in plan.error
    assert cut.purpose == LLMCallPurpose.STANCE_REVIEW and cut.error.startswith("budget_exceeded")


async def test_no_reviewer_means_no_review():
    fake = FakeLLMClient([json.dumps(VALID_CASE_FILE)])
    outcome = await generate_case_file(MOTION, CON, PRO, OpponentDifficulty.MEDIUM, fake, _settings())
    assert [a.purpose for a in outcome.attempts] == [LLMCallPurpose.CASE_PLAN]
    assert outcome.attempts[0].reviewer_verdict is None and outcome.reviewer_model is None


# ---------------- stance_review_v2: doc them reasoning ----------------

# Nguyen van v4 batch 20260927-094713, M10 "Nên đánh thuế cao đối với đồ uống có đường", ai_side=con, medium, lan
# thu #1: reviewer v1 (chi doc claim) bao A3 = ung_ho (bo sot phu dinh "không chắc chắn") -> side_flip SAI;
# nguoi gan nhan: A3 = phan_doi (dung phe).
M10_MOTION = "Nên đánh thuế cao đối với đồ uống có đường"
M10_ARGS = [
    ("A1", "Mức thuế cao sẽ làm tăng chi phí sinh hoạt cho các hộ gia đình thu nhập thấp.",
     "Thuế được tính trên mỗi đơn vị sản phẩm, vì vậy mọi người tiêu dùng phải trả thêm cho cùng một lượng đồ uống. "
     "Người thu nhập thấp chi tiêu tỷ lệ lớn hơn thu nhập của mình cho thực phẩm và đồ uống thiết yếu, nên phần tăng "
     "giá sẽ chiếm tỷ lệ cao hơn trong ngân sách của họ so với người có thu nhập cao."),
    ("A2", "Mức thuế cao sẽ tạo ra động lực cho hoạt động buôn lậu và sản xuất đồ uống không có thuế.",
     "Khi giá hợp pháp tăng mạnh, người tiêu dùng tìm kiếm các nguồn cung cấp rẻ hơn. Điều này khuyến khích các nhóm "
     "kinh doanh bất hợp pháp sản xuất hoặc nhập khẩu đồ uống có đường không chịu thuế, dẫn đến thị trường ngầm phát triển."),
    ("A3", "Giá tăng do thuế không chắc chắn dẫn đến giảm đáng kể việc tiêu thụ đồ uống có đường.",
     "Thói quen tiêu dùng nước ngọt ở nhiều người Việt, đặc biệt là thanh thiếu niên, dựa vào yếu tố thói quen và "
     "cảm giác thèm, không chỉ phụ thuộc vào giá cả. Khi giá tăng, một số người vẫn sẽ mua vì ưu tiên thói quen hơn "
     "là chi phí, hoặc chuyển sang các loại đồ uống có đường khác không bị đánh thuế."),
]
M10_WEIGHING = (
    "Khi cân nhắc tổng thể, phe phản đối thắng vì thuế cao gây bất lợi rõ rệt cho các hộ gia đình thu nhập thấp, "
    "kích thích thị trường chợ đen làm mất thu nhập nhà nước, và không đảm bảo giảm tiêu thụ đường một cách hiệu quả."
)


def _m10_case_file() -> str:
    data = json.loads(json.dumps(VALID_CASE_FILE))
    for arg, (arg_id, claim, reasoning) in zip(data["arguments"], M10_ARGS):
        arg.update(id=arg_id, claim=claim, reasoning=reasoning)
    data["weighing"] = M10_WEIGHING
    return json.dumps(data, ensure_ascii=False)


def test_default_review_prompt_is_v1_and_max_tokens_2000():
    s = _settings()
    assert s.stance_review_prompt_version == "stance_review_v1"  # muc 2.4m (v3 bao sai 3/3 o batch v5)
    assert s.stance_review_max_tokens == 2000


def test_v2_prompt_includes_reasoning_but_no_side():
    statements = [sr.Statement(i, c, r) for i, c, r in M10_ARGS]
    system, user = sr.build_review_prompt_v2(M10_MOTION, statements, M10_WEIGHING)
    assert list(inspect.signature(sr.build_review_prompt_v2).parameters) == ["motion", "statements", "summary"]
    assert '- [A3] Khẳng định: "Giá tăng do thuế không chắc chắn dẫn đến giảm đáng kể việc tiêu thụ đồ uống có đường."' in user
    assert f'  Lý do: "{M10_ARGS[2][2]}"' in user
    assert "không chắc chắn" in system  # nhac chu y phu dinh
    for leak in ("Đề xuất", "Phản đối", "phe của bạn", "Bạn thuộc phe"):
        assert leak not in system + user
    _, user_v1 = sr.build_review_prompt(M10_MOTION, statements, M10_WEIGHING)
    assert M10_ARGS[2][2] not in user_v1  # v1 giu nguyen: chi claim


async def test_regression_m10_a3_reviewer_v2_reads_reasoning():
    reviewer = FakeStanceReviewer(PHAN_DOI)  # mock: doc duoc ly do -> A3 phan doi (dung nhu nguoi gan nhan)
    outcome = await generate_case_file(
        M10_MOTION, CON, PRO, OpponentDifficulty.MEDIUM, FakeLLMClient([_m10_case_file()]),
        _settings(stance_review_prompt_version="stance_review_v2"), reviewer,
    )

    user = reviewer.calls[0]["user"]
    assert M10_ARGS[2][1] in user and M10_ARGS[2][2] in user  # prompt co claim + reasoning cua A3
    plan, review = outcome.attempts
    assert plan.reviewer_verdict == ReviewerVerdict.PASS and outcome.case_file is not None
    a3 = next(p for p in plan.reviewer_detail["positions"] if p["id"] == "A3")
    assert a3["position"] == PHAN_DOI
    assert plan.reviewer_detail["prompt_version"] == review.prompt_version == "stance_review_v2"


async def test_v1_is_default():
    reviewer = FakeStanceReviewer(PHAN_DOI)
    outcome = await generate_case_file(
        M10_MOTION, CON, PRO, OpponentDifficulty.MEDIUM, FakeLLMClient([_m10_case_file()]), _settings(), reviewer
    )
    assert M10_ARGS[2][2] not in reviewer.calls[0]["user"]
    assert outcome.attempts[1].prompt_version == "stance_review_v1"



# ---------------- stance_review_v3: dien dat lai -> "manh hon / yeu di" ----------------


def test_v3_prompt_input_like_v2_no_side_and_asks_effect():
    statements = [sr.Statement(i, c, r) for i, c, r in M10_ARGS]
    system, user = sr.build_review_prompt_v3(M10_MOTION, statements, M10_WEIGHING)
    _, user_v2 = sr.build_review_prompt_v2(M10_MOTION, statements, M10_WEIGHING)
    assert list(inspect.signature(sr.build_review_prompt_v3).parameters) == ["motion", "statements", "summary"]
    # phan noi dung (luan diem + ket luan) giong het v2; chi khac cau huong dan dinh dang
    assert user.split("\n\nTrả về JSON:")[0] == user_v2.split("\n\nTrả về JSON:")[0]
    assert f'  Lý do: "{M10_ARGS[2][2]}"' in user
    assert '"restatement", "effect", "reason"' in user
    assert "Nếu luận điểm này đúng, kiến nghị trở nên mạnh hơn hay yếu đi?" in system
    assert "MỘT câu đơn giản, không phủ định lồng" in system
    for leak in ("Đề xuất", "Phản đối", "phe của bạn", "Bạn thuộc phe", "ung_ho_kien_nghi", "phan_doi_kien_nghi"):
        assert leak not in system + user


def test_v3_schema_field_order_restatement_effect_reason():
    schema = sr.build_review_schema_v3(["A1", "A2", "A3"], has_summary=True)
    item = schema["properties"]["arguments"]["items"]
    assert list(item["properties"]) == ["id", "restatement", "effect", "reason"]
    assert item["required"] == ["id", "restatement", "effect", "reason"]
    assert item["properties"]["effect"]["enum"] == ["manh_hon", "yeu_di", "khong_ro"]
    weighing = schema["properties"]["weighing"]
    assert list(weighing["properties"]) == weighing["required"] == ["restatement", "effect", "reason"]
    # key "restatement" dung TRUOC "effect" trong JSON gui provider (thu tu dict duoc giu khi json.dumps)
    dumped = json.dumps(schema)
    assert dumped.index('"restatement"') < dumped.index('"effect"') < dumped.index('"reason"')
    assert schema["additionalProperties"] is False and item["additionalProperties"] is False


@pytest.mark.parametrize(
    "effect,ai_side,verdict",
    [("manh_hon", PRO, ReviewerVerdict.PASS), ("yeu_di", CON, ReviewerVerdict.PASS),
     ("yeu_di", PRO, ReviewerVerdict.SIDE_FLIP), ("manh_hon", CON, ReviewerVerdict.SIDE_FLIP),
     ("khong_ro", PRO, ReviewerVerdict.UNCLEAR)],
)
def test_v3_effect_maps_to_position_and_side_flip_logic_unchanged(effect, ai_side, verdict):
    fine = "manh_hon" if ai_side == PRO else "yeu_di"
    raw = json.dumps({
        "arguments": [{"id": "A1", "restatement": "r1", "effect": effect, "reason": "x"},
                      {"id": "A2", "restatement": "r2", "effect": fine, "reason": "x"}],
        "weighing": {"restatement": "rw", "effect": fine, "reason": "x"},
    })
    review, extra = sr.parse_review_v3(raw, ["A1", "A2"], has_summary=True)
    got, detail = sr.judge(review, ai_side, sr.PROMPT_VERSION_V3, extra)
    assert got == verdict
    a1 = detail["positions"][0]
    assert a1["position"] == sr.EFFECT_TO_POSITION[sr.Effect(effect)].value
    assert (a1["restatement"], a1["effect"]) == ("r1", effect)
    assert detail["positions"][-1]["id"] == "weighing" and detail["positions"][-1]["restatement"] == "rw"


@pytest.mark.parametrize(
    "bad",
    [
        {"arguments": [{"id": "A1", "position": "phan_doi_kien_nghi", "reason": "x"}],  # dinh dang v1
         "weighing": {"restatement": "r", "effect": "yeu_di", "reason": "x"}},
        {"arguments": [{"id": "A1", "restatement": "", "effect": "yeu_di", "reason": "x"}],  # restatement rong
         "weighing": {"restatement": "r", "effect": "yeu_di", "reason": "x"}},
        {"arguments": [{"id": "A1", "restatement": "r", "effect": "yeu_di", "reason": "x"}]},  # thieu weighing
    ],
)
def test_v3_parse_rejects_bad_output(bad):
    with pytest.raises((ValidationError, ValueError)):
        sr.parse_review_v3(json.dumps(bad), ["A1"], has_summary=True)


async def test_regression_m10_a3_reviewer_v3():
    reviewer = FakeStanceReviewer(PHAN_DOI)  # mock: dien dat lai dung -> A3 "yeu_di" (phan doi, dung phe con)
    outcome = await generate_case_file(
        M10_MOTION, CON, PRO, OpponentDifficulty.MEDIUM, FakeLLMClient([_m10_case_file()]),
        _settings(stance_review_prompt_version="stance_review_v3"), reviewer,
    )

    call = reviewer.calls[0]
    assert M10_ARGS[2][1] in call["user"] and M10_ARGS[2][2] in call["user"]
    assert call["json_schema"] == sr.build_review_schema_v3(["A1", "A2", "A3"], has_summary=True)
    plan, review = outcome.attempts
    assert plan.reviewer_verdict == ReviewerVerdict.PASS and outcome.case_file is not None
    a3 = next(p for p in plan.reviewer_detail["positions"] if p["id"] == "A3")
    assert (a3["position"], a3["effect"], a3["restatement"]) == (PHAN_DOI, "yeu_di", "dien dat lai A3")
    assert review.prompt_version == plan.reviewer_detail["prompt_version"] == "stance_review_v3"


async def test_v3_reviewer_error_is_unclear_not_blocking():
    reviewer = FakeStanceReviewer(PHAN_DOI)
    bad = json.dumps({"arguments": [{"id": "A1", "position": PHAN_DOI, "reason": "x"}]})  # sai dinh dang v3
    reviewer.responses = [bad, bad]
    outcome = await _plan(FakeLLMClient([json.dumps(VALID_CASE_FILE)]), reviewer,
                          stance_review_prompt_version="stance_review_v3")
    assert outcome.case_file is not None
    assert outcome.attempts[0].reviewer_verdict == ReviewerVerdict.UNCLEAR
    assert outcome.attempts[0].reviewer_detail["prompt_version"] == "stance_review_v3"
