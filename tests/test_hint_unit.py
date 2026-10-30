"""
Goi y phan bac (WF-02) — phan THUAN (hint.py, hint_service.target_turn_for / build_context). Khong DB, LLM gia.
"""
import ast
import inspect
import json

import pytest

from app.core.config import Settings
from app.opponent import hint as h
from app.opponent import hint_service as hs
from app.opponent.models import DebateSide, OpponentSession, OpponentSpeech, RoundType, Speaker
from app.opponent.schemas import AttackType, CreateHintRequest, HintStrategy
from tests.conftest import FakeLLMClient, FakeStanceReviewer

PRO, CON = DebateSide.PRO, DebateSide.CON
SETTINGS = Settings(_env_file=None)
MOTION = "Nên cấm học sinh sử dụng điện thoại trong trường học"
CASE_MARKER = "MARKER_CASE_PLAN_7731"
TARGET_TEXT = ("Điện thoại làm học sinh mất tập trung trong giờ học. Cấm điện thoại giúp giảm bắt nạt trên mạng. "
               "Liên lạc khẩn cấp đã có điện thoại của giám thị.")


def S(title="Chỉ ra tiền đề ngầm", claim="Điện thoại làm học sinh mất tập trung", attack="hidden_premise",
      direction="Hỏi xem mất tập trung do điện thoại hay do cách quản lý lớp.", evidence="Tình huống thực tế ở lớp học"):
    return {"title": title, "target_claim": claim, "attack_type": attack, "direction": direction,
            "evidence_to_look_for": evidence}


def OUT(*strategies) -> str:
    return json.dumps({"strategies": list(strategies) or [S(), S(claim="Cấm giúp giảm bắt nạt", attack="counterexample")]},
                      ensure_ascii=False)


def _ctx(learner_side=CON, history=(), draft=None, target_text=TARGET_TEXT) -> h.HintContext:
    return h.HintContext(
        motion=MOTION, learner_side=learner_side, learner_turn_index=2, learner_round_type=RoundType.OPENING,
        target=h.PublicSpeech(1, RoundType.OPENING, Speaker.AI, target_text), history=list(history),
        learner_draft=draft,
    )


# ---------------- map luot (spec muc 3) ----------------


@pytest.mark.parametrize("ai_side,learner_turn,target", [
    (CON, 3, 2), (CON, 6, 5),  # learner pro
    (PRO, 2, 1), (PRO, 4, 3), (PRO, 5, 3),  # learner con
])
def test_target_turn_mapping(ai_side, learner_turn, target):
    assert hs.target_turn_for(learner_turn, ai_side) == target


@pytest.mark.parametrize("ai_side,learner_turn,message", [
    (CON, 1, "Chua co luot AI"),  # learner pro xin o luot 1
    (CON, 2, "la luot cua AI"), (CON, 4, "la luot cua AI"), (CON, 5, "la luot cua AI"),
    (PRO, 1, "la luot cua AI"), (PRO, 3, "la luot cua AI"), (PRO, 6, "la luot cua AI"),
    (PRO, 0, "khong ton tai"), (CON, 7, "khong ton tai"),
])
def test_target_turn_invalid(ai_side, learner_turn, message):
    with pytest.raises(hs.HintRequestError, match=message):
        hs.target_turn_for(learner_turn, ai_side)


# ---------------- KHONG doc case plan (spec muc 4) ----------------


def test_prompt_builder_has_no_case_file_parameter():
    assert list(inspect.signature(h.build_hint_prompt).parameters) == ["context", "feedback"]
    assert {f for f in h.HintContext.__dataclass_fields__} == {
        "motion", "learner_side", "learner_turn_index", "learner_round_type", "target", "history", "learner_draft"}
    # Quet AST (bo docstring / comment): khong ten nao trong code cham toi case file / ledger / phan tich noi bo.
    names = set()
    for mod in (h, hs):
        for node in ast.walk(ast.parse(inspect.getsource(mod))):
            if isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                names.add(node.attr)
            elif isinstance(node, ast.alias):
                names.add(node.name)
    forbidden = {"get_case_file", "build_ledger", "Ledger", "OpponentCaseFile", "OpponentTurn", "case_file",
                 "ai_points", "premises", "target_premise", "learner_claims"}
    assert names & forbidden == set()


def test_build_context_ignores_case_file_and_prompt_has_no_marker():
    session = OpponentSession(motion=MOTION, ai_side=PRO, learner_side=CON)
    session.case_file = None  # quan he ORM khong duoc dung; context chi lay tu speeches
    speeches = {1: OpponentSpeech(turn_index=1, round_type=RoundType.OPENING, speaker=Speaker.AI, text=TARGET_TEXT)}
    ctx = hs.build_context(session, 2, 1, speeches, None)
    case_like = {"arguments": [{"claim": CASE_MARKER, "reasoning": CASE_MARKER}], "weighing": CASE_MARKER}
    ctx_dict = vars(ctx) | {"target": vars(ctx.target)}
    assert CASE_MARKER not in json.dumps(ctx_dict, ensure_ascii=False, default=str)
    system, user = h.build_hint_prompt(ctx)
    assert CASE_MARKER not in system + user and json.dumps(case_like) not in user
    assert TARGET_TEXT in user


# ---------------- prompt + rut gon lich su ----------------


def test_history_includes_learner_turn_after_target():
    # learner con luot 5: target = luot 3 (AI); luot 4 cua CHINH learner nam giua target va luot 5 -> phai co trong lich su
    session = OpponentSession(motion=MOTION, ai_side=PRO, learner_side=CON)
    speeches = {t: OpponentSpeech(turn_index=t, round_type=rt, speaker=sp, text=f"Bài lượt {t}.")
                for t, rt, sp in ((1, RoundType.OPENING, Speaker.AI), (2, RoundType.OPENING, Speaker.LEARNER),
                                  (3, RoundType.REBUTTAL, Speaker.AI), (4, RoundType.REBUTTAL, Speaker.LEARNER))}
    ctx = hs.build_context(session, 5, 3, speeches, None)
    assert ctx.target.turn_index == 3 and [s.turn_index for s in ctx.history] == [1, 2, 4]
    _, user = h.build_hint_prompt(ctx)
    assert "Lượt 4 – Học sinh" in user and "lượt 3, nguyên văn" in user


def test_history_truncated_target_verbatim():
    long_old = " ".join(f"cu{i}" for i in range(400))
    long_target = " ".join(f"moi{i}" for i in range(400))
    history = [h.PublicSpeech(1, RoundType.OPENING, Speaker.AI, long_old),
               h.PublicSpeech(2, RoundType.OPENING, Speaker.LEARNER, "Bài mở màn của học sinh.")]
    ctx = h.HintContext(MOTION, PRO, 4, RoundType.REBUTTAL, h.PublicSpeech(3, RoundType.REBUTTAL, Speaker.AI, long_target),
                        history)
    _, user = h.build_hint_prompt(ctx)
    assert long_target in user  # target nguyen van
    assert "cu149 …" in user and "cu150" not in user  # luot cu: 150 tu dau
    assert "Bài mở màn của học sinh." in user
    assert h.truncate_words("a b c", 5) == "a b c"


def test_prompt_contents_and_draft():
    _, user = h.build_hint_prompt(_ctx(draft="Mình định nói về quyền liên lạc."))
    assert "Học sinh thuộc phe Phản đối; đối thủ thuộc phe Đề xuất" in user
    assert "phần mở màn (lượt 2)" in user and "Mình định nói về quyền liên lạc." in user
    assert "Mọi chiến lược phải giúp phe Phản đối" in user
    _, no_draft = h.build_hint_prompt(_ctx())
    assert "Bản nháp" not in no_draft


def test_schema_enum_and_counts():
    schema = h.build_hint_schema()["properties"]["strategies"]
    assert (schema["minItems"], schema["maxItems"]) == (2, 3)
    assert schema["items"]["properties"]["attack_type"]["enum"] == [a.value for a in AttackType]
    assert schema["items"]["required"] == list(h.FIELD_ORDER)


# ---------------- validator ----------------


@pytest.mark.parametrize("raw,kind", [
    ("khong phai json", "invalid_json"),
    (OUT(S()), "schema_validation"),  # 1 chien luoc
    (OUT(S(), S(attack="logical_gap"), S(attack="counterexample"), S(attack="weak_evidence")), "schema_validation"),
    (OUT(S(), S(attack="ad_hominem")), "schema_validation"),  # ngoai enum
    (json.dumps({"strategies": [{"title": "x"}, {"title": "y"}]}), "schema_validation"),  # thieu truong
    (OUT(S(), S(attack="counterexample", direction=" ".join(["từ"] * 61))), "direction_too_long"),
    (OUT(S(), S(claim="Cấm giúp giảm bắt nạt", attack="counterexample", evidence="Khảo sát 80% học sinh")),
     "fabricated_evidence"),
    (OUT(S(), S(claim="Cấm giúp giảm bắt nạt", attack="counterexample", evidence="Bài viết trên www.abc.vn")),
     "fabricated_evidence"),
    (OUT(S(), S(claim="Cấm giúp giảm bắt nạt", attack="counterexample",
                evidence="Nghiên cứu của trường đại học cho thấy điều ngược lại")), "fabricated_evidence"),
    # direction cung bi kiem tra (ca that 2026-10-31: "vi nghien cuu cho thay..." lot qua o direction)
    (OUT(S(), S(claim="Cấm giúp giảm bắt nạt", attack="counterexample",
                direction="Chỉ ra giả định tự giác chưa được chứng minh, vì nghiên cứu cho thấy tuổi teen thiếu tự kiểm soát.")),
     "fabricated_evidence"),
    (OUT(S(), S(claim="Cấm giúp giảm bắt nạt", attack="counterexample", direction="Nêu rằng 70% vụ bắt nạt xảy ra ở nhà.")),
     "fabricated_evidence"),
    (OUT(S(), S(claim="điện thoại  làm học sinh MẤT tập trung!")), "duplicate_strategy"),  # trung sau chuan hoa
])
def test_validator_rejects(raw, kind):
    with pytest.raises(h.InvalidHint) as e:
        h.parse_hint_output(raw)
    assert e.value.kind == kind and e.value.issues


def test_validator_feedback_names_direction_field():
    raw = OUT(S(), S(claim="Cấm giúp giảm bắt nạt", attack="counterexample", direction="Theo thống kê 2023, bắt nạt tăng."))
    with pytest.raises(h.InvalidHint) as e:
        h.parse_hint_output(raw)
    assert len(e.value.issues) == 1 and "`strategies.1.direction`" in e.value.issues[0]


def test_validator_accepts_boundaries():
    exactly_60 = " ".join(["từ"] * 60)
    out = h.parse_hint_output(OUT(S(direction=exactly_60, evidence=None), S(attack="counterexample"),
                                  S(claim="Cấm giúp giảm bắt nạt", attack="hidden_premise")))  # 3 chien luoc
    assert len(out) == 3 and out[0].evidence_to_look_for is None
    # cung target_claim nhung khac attack_type -> hop le
    assert len(h.parse_hint_output(OUT(S(), S(attack="counterexample")))) == 2


def test_target_overlap_log_only():
    strategies = [HintStrategy(**S()), HintStrategy(**S(claim="Điều đối thủ không hề nói tới"))]
    high, low = h.target_overlap(strategies, TARGET_TEXT)
    assert high == 1.0 and low < 0.5


@pytest.mark.parametrize("turn", [0, 7, -1])
def test_learner_turn_index_out_of_range_rejected_by_schema(turn):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        CreateHintRequest(request_id="r", learner_turn_index=turn)


def test_draft_normalized():
    assert CreateHintRequest(request_id=" r1 ", learner_turn_index=2, learner_draft="   ").learner_draft is None
    assert CreateHintRequest(request_id="r1", learner_turn_index=2).request_id == "r1"


# ---------------- bo sinh (LLM gia) ----------------


def _reviewer(learner_side=CON):
    return FakeStanceReviewer("phan_doi_kien_nghi" if learner_side == CON else "ung_ho_kien_nghi")


async def test_generator_ok_logs_and_uses_settings():
    fake = FakeLLMClient([OUT()])
    fake.usages = [{"tokens_in": 900, "tokens_out": 300}]
    reviewer = _reviewer()
    result = await h.HintGenerator(fake, SETTINGS, reviewer).generate(_ctx())
    assert result.strategies and len(result.strategies) == 2
    call = fake.calls[0]
    assert call["max_tokens"] == SETTINGS.hint_max_tokens == 2000
    assert call["temperature"] == SETTINGS.llm_temperature and call["reasoning_effort"] == "low"
    assert call["json_schema"] == h.build_hint_schema()
    assert [c.purpose.value for c in result.calls] == ["hint", "stance_review"]
    assert result.tokens("tokens_in") == 900 and result.calls[0].speech_checks["target_overlap"]
    # reviewer KHONG biet phe, chi thay motion + chien luoc
    assert "Phản đối" not in reviewer.calls[0]["user"] and "[H1]" in reviewer.calls[0]["user"]


async def test_generator_retries_with_feedback_then_fails():
    fake = FakeLLMClient(["hong", OUT(S()), "van hong"])
    result = await h.HintGenerator(fake, SETTINGS, None).generate(_ctx())
    assert result.strategies is None and result.failure_kind == "invalid_json"
    assert [c.failure_kind for c in result.calls] == ["invalid_json", "schema_validation", "invalid_json"]
    assert "GHI CHÚ" in fake.calls[1]["user"] or "chưa hợp lệ" in fake.calls[1]["user"].lower() or \
        result.calls[0].retry_feedback in fake.calls[1]["user"]


async def test_generator_side_flip_neutral_retry():
    fake = FakeLLMClient([OUT(), OUT()])
    reviewer = _reviewer()
    reviewer.responses = [json.dumps({"arguments": [
        {"id": "H1", "position": "ung_ho_kien_nghi", "reason": "x"},
        {"id": "H2", "position": "phan_doi_kien_nghi", "reason": "x"}]})]
    result = await h.HintGenerator(fake, SETTINGS, reviewer).generate(_ctx())
    assert result.strategies is not None
    gen = [c for c in result.calls if c.purpose.value == "hint"]
    assert gen[0].failure_kind == "side_flip" and gen[0].retry_feedback is None
    assert fake.calls[0]["user"] == fake.calls[1]["user"]  # trung tinh: prompt goc


async def test_generator_reviewer_failure_is_fail_closed():
    fake = FakeLLMClient([OUT()] * SETTINGS.hint_max_attempts)
    reviewer = _reviewer()
    reviewer.responses = ["hong"] * (2 * SETTINGS.hint_max_attempts)
    result = await h.HintGenerator(fake, SETTINGS, reviewer).generate(_ctx())
    assert result.strategies is None and result.failure_kind == "reviewer_unavailable"


async def test_generator_provider_error():
    fake = FakeLLMClient([RuntimeError("503 down")])
    result = await h.HintGenerator(fake, SETTINGS, None).generate(_ctx())
    assert result.strategies is None and result.failure_kind == "provider_error"


async def test_run_hint_budget_exceeded(monkeypatch):
    fake = FakeLLMClient([OUT()])
    fake.delay_seconds = 0.5
    settings = SETTINGS.model_copy(update={"hint_total_budget_seconds": 0.05})
    result = await h.run_hint(_ctx(), fake, settings, None)
    assert result.strategies is None and result.failure_kind == "budget_exceeded"
