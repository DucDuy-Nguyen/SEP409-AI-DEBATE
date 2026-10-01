"""
Giai doan 3c (muc 2.11): Stance Reviewer cho luot noi (turn_full_v*) + gon token (ep rong phan tich). LLM gia.
"""
import json

import pytest
from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.main import app
from app.opponent import turn_full as tf
from app.opponent.match_format import TurnMode
from app.opponent.models import (
    DebateSide,
    LLMCallPurpose,
    OpponentLLMCall,
    OpponentSpeech,
    OpponentTurn,
    ReviewerVerdict,
)
from tests.conftest import FakeLLMClient, FakeStanceReviewer
from tests.test_turn_full import CASE, _ctx, _out, _sp
from tests.test_turns_api import _learner, _ready_session, _session_id, _turn

PRO, CON = DebateSide.PRO, DebateSide.CON
UH, PD = "ung_ho_kien_nghi", "phan_doi_kien_nghi"


def _flipped(ids=("P1", "P2")) -> str:
    """Output reviewer v1: moi muc UNG HO kien nghi (= nguoc phe AI con)."""
    return json.dumps({"arguments": [{"id": i, "position": UH, "reason": "lat"} for i in ids],
                       "weighing": {"position": UH, "reason": "lat"}})


async def _calls(db_session, ext, purpose=None):
    """Loi goi cua cac LUOT NOI (bo loi goi Case Planning + reviewer cua Case Planning: tao truoc luot noi dau)."""
    sid = await _session_id(db_session, ext)
    q = select(OpponentLLMCall).where(OpponentLLMCall.session_id == sid)
    rows = (await db_session.scalars(q.order_by(OpponentLLMCall.created_at))).all()
    first_turn = next(i for i, r in enumerate(rows) if r.purpose == LLMCallPurpose.TURN)
    rows = sorted(rows[first_turn:], key=lambda r: (r.created_at, r.attempt))
    return [r for r in rows if purpose is None or r.purpose == purpose]


def _planner_calls(fake_llm):
    return [c for c in fake_llm.calls if "user" in c and not c.get("chat")]


# ---------------- reviewer nhan gi ----------------


async def test_reviewer_gets_ai_points_and_speech_but_not_ai_side():
    prompts = []
    for ai_side in (PRO, CON):
        reviewer = FakeStanceReviewer(UH if ai_side == PRO else PD)
        gen = tf.FullTurnGeneratorV2(FakeLLMClient([_out(TurnMode.CLOSING)]), Settings(_env_file=None), reviewer)
        turn = 6 if ai_side == PRO else 5
        result = await gen.generate(TurnMode.CLOSING, _ctx(ai_side, turn))
        assert result.text is not None
        prompts.append((reviewer.calls[0]["system"], reviewer.calls[0]["user"], reviewer.calls[0]))

    (sys_pro, user_pro, call), (sys_con, user_con, _) = prompts
    assert (sys_pro, user_pro) == (sys_con, user_con)  # CUNG output, KHAC phe -> reviewer nhan prompt GIONG HET
    assert '- [P1] "Ý thứ nhất của mình."' in user_pro and '- [P2] "Ý thứ hai của mình."' in user_pro
    assert "Phần kết luận / cân nhắc tổng thể của đội đó:" in user_pro
    assert user_pro.startswith("Một đội tranh luận đưa ra các luận điểm sau về kiến nghị")  # ngoi thu ba
    speech = json.loads(_out(TurnMode.CLOSING))["speech_text"]
    assert speech in user_pro
    for leak in ("Đề xuất", "Phản đối", "phe của bạn"):
        assert leak not in sys_pro + user_pro
    assert call["temperature"] == 0.0 and call["reasoning_effort"] is None  # khong gui TURN_REASONING_EFFORT
    assert call["json_schema"]["properties"]["arguments"]["minItems"] == 2


# ---------------- side_flip ----------------


async def test_side_flip_retries_neutrally_without_feedback(client, db_session, fake_llm, fake_reviewer):
    ext = await _ready_session(client, fake_llm, fake_reviewer, "con")
    fake_reviewer.calls.clear()
    fake_reviewer.responses = [_flipped()]  # lan review dau: lat phe; sau do mac dinh phan_doi (dung phe con)
    fake_llm.responses = [_out(TurnMode.OPENING_REPLY), _out(TurnMode.OPENING_REPLY)]

    resp = await _turn(client, ext, 2, [_learner(1)])
    assert resp.status_code == 201, resp.text

    first, second = _planner_calls(fake_llm)
    assert second["user"] == first["user"]  # TRUNG TINH: dung prompt goc
    assert "PHẢN HỒI" not in second["user"] and "lật phe" not in second["user"]
    rows = await _calls(db_session, ext)
    assert [(r.purpose.value, r.attempt, r.success, r.failure_kind) for r in rows] == [
        ("turn", 1, False, "side_flip"), ("stance_review", 2, True, None),
        ("turn", 3, True, None), ("stance_review", 4, True, None),
    ]
    flipped, review1, accepted, review2 = rows
    assert flipped.reviewer_verdict == ReviewerVerdict.SIDE_FLIP and flipped.retry_feedback is None
    assert flipped.reviewer_detail["retry"] == "side_flip_neutral_retry"
    assert flipped.reviewer_detail["flipped_ids"] == ["P1", "P2", "weighing"]
    assert review1.reviewer_verdict == ReviewerVerdict.SIDE_FLIP and review1.llm_model == "fake-reviewer"
    assert review1.prompt_version == "stance_review_v1" and review1.temperature == 0.0
    assert accepted.reviewer_verdict == review2.reviewer_verdict == ReviewerVerdict.PASS
    assert all(r.turn_id == accepted.turn_id is not None for r in rows)


async def test_side_flip_every_attempt_is_502_and_speech_not_saved(client, db_session, fake_llm, fake_reviewer):
    ext = await _ready_session(client, fake_llm, fake_reviewer, "con")
    fake_reviewer.default_position = UH  # moi lan review: nguoc phe AI con
    fake_llm.responses = [_out(TurnMode.OPENING_REPLY)] * 3

    resp = await _turn(client, ext, 2, [_learner(1)])
    assert resp.status_code == 502 and "side_flip" in resp.json()["detail"]

    sid = await _session_id(db_session, ext)
    assert await db_session.scalar(select(OpponentSpeech).where(
        OpponentSpeech.session_id == sid, OpponentSpeech.turn_index == 2)) is None  # KHONG luu bai lat phe
    assert await db_session.scalar(select(OpponentTurn).where(OpponentTurn.session_id == sid)) is None
    rows = await _calls(db_session, ext)
    assert len(_planner_calls(fake_llm)) == 3  # side_flip tinh vao TURN_MAX_ATTEMPTS
    assert [r.failure_kind for r in rows if r.purpose == LLMCallPurpose.TURN] == ["side_flip"] * 3
    assert all(r.turn_id is None and r.reviewer_verdict == ReviewerVerdict.SIDE_FLIP for r in rows)


async def test_side_flip_never_returned_even_if_earlier_attempt_only_had_length_issue(
    client, db_session, fake_llm, fake_reviewer
):
    # Lan 1: dung phe nhung dai 700 tu (ung vien); lan 2, 3: lat phe -> chap nhan LAN 1 (khong phai ban lat phe)
    ext = await _ready_session(client, fake_llm, fake_reviewer, "con")
    reviews = iter([None, _flipped(), _flipped()])  # None = review that (fake mac dinh: dung phe)

    orig = fake_reviewer.generate

    def generate(*args, **kwargs):
        item = next(reviews, None)
        return item if item is not None else orig(*args, **kwargs)

    fake_reviewer.generate = generate
    fake_llm.responses = [_out(TurnMode.OPENING_REPLY, n_words=560), _out(TurnMode.OPENING_REPLY),
                          _out(TurnMode.OPENING_REPLY)]
    resp = await _turn(client, ext, 2, [_learner(1)])
    assert resp.status_code == 201, resp.text
    assert resp.json()["speech_text"].count(" ") == 559  # ban 560 tu, da qua reviewer


# ---------------- unclear / reviewer loi ----------------


async def test_unclear_is_accepted_and_logged(client, db_session, fake_llm, fake_reviewer):
    ext = await _ready_session(client, fake_llm, fake_reviewer, "con")
    fake_reviewer.positions = {"P2": "khong_ro"}
    fake_llm.responses = [_out(TurnMode.OPENING_REPLY)]
    assert (await _turn(client, ext, 2, [_learner(1)])).status_code == 201
    turn_row = (await _calls(db_session, ext, LLMCallPurpose.TURN))[0]
    assert turn_row.success and turn_row.reviewer_verdict == ReviewerVerdict.UNCLEAR
    assert turn_row.reviewer_detail["unclear_ids"] == ["P2"]


async def test_reviewer_error_twice_counts_as_unclear(client, db_session, fake_llm, fake_reviewer):
    ext = await _ready_session(client, fake_llm, fake_reviewer, "con")
    fake_reviewer.responses = ["khong phai json", RuntimeError("503 reviewer down")]
    fake_llm.responses = [_out(TurnMode.OPENING_REPLY)]
    assert (await _turn(client, ext, 2, [_learner(1)])).status_code == 201
    rows = await _calls(db_session, ext)
    assert [(r.purpose.value, r.success, r.failure_kind) for r in rows] == [
        ("turn", True, None), ("stance_review", False, "reviewer_error"), ("stance_review", False, "provider_error"),
    ]
    assert rows[0].reviewer_verdict == ReviewerVerdict.UNCLEAR and "reviewer_error" in rows[0].reviewer_detail
    assert len(_planner_calls(fake_llm)) == 1  # reviewer loi KHONG tinh vao TURN_MAX_ATTEMPTS


# ---------------- baseline + tat reviewer ----------------


async def test_baseline_never_calls_reviewer(client, fake_llm, fake_reviewer):
    ext = await _ready_session(client, fake_llm, fake_reviewer, "con")
    fake_reviewer.calls.clear()
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, turn_generator_version="turn_baseline_v1")
    fake_llm.responses = ["Bài mở màn baseline."]
    assert (await _turn(client, ext, 2, [_learner(1)])).status_code == 201
    assert fake_reviewer.calls == []


async def test_review_disabled_skips_review(client, fake_llm, fake_reviewer):
    ext = await _ready_session(client, fake_llm, fake_reviewer, "con")
    fake_reviewer.calls.clear()
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, stance_review_enabled=False)
    from app.opponent.router import get_stance_reviewer_factory

    app.dependency_overrides[get_stance_reviewer_factory] = lambda: (lambda: None)  # nhu factory that khi tat
    fake_llm.responses = [_out(TurnMode.OPENING_REPLY)]
    assert (await _turn(client, ext, 2, [_learner(1)])).status_code == 201
    assert fake_reviewer.calls == []


# ---------------- gon token ----------------


def test_prompt_and_schema_when_no_new_learner_speech():
    history = [_sp(1, CON, "Mở màn learner."), _sp(2, CON, "AI 2."), _sp(3, CON, "Phản bác learner."), _sp(4, CON, "AI 4.")]
    _, user = tf.build_full_prompt(TurnMode.CLOSING, _ctx(CON, 5, history))
    assert tf.NO_NEW_SPEECH in user and "vừa phát biểu" not in user
    assert "- learner_claims: [] (không có bài nói mới)." in user
    assert "để cả hai mảng rỗng (không có bài nói mới để phân tích)" in user
    schema = tf.build_response_schema(TurnMode.CLOSING, has_new_speech=False)
    assert schema["properties"]["learner_claims"]["maxItems"] == 0
    assert schema["properties"]["premises"]["properties"]["explicit"]["maxItems"] == 0
    # closing CO bai moi (AI pro luot 6): trich learner_claims, nhung KHONG phan tich tien de
    with_new = tf.build_response_schema(TurnMode.CLOSING, has_new_speech=True)
    assert "maxItems" not in with_new["properties"]["learner_claims"]
    assert with_new["properties"]["premises"]["properties"]["implicit"]["maxItems"] == 0
    _, user6 = tf.build_full_prompt(TurnMode.CLOSING, _ctx(PRO, 6, [_sp(5, PRO, "Tổng kết learner.")]))
    assert "lượt tổng kết không phân tích tiền đề" in user6 and tf.NO_NEW_SPEECH not in user6
    # rebuttal van phan tich day du
    assert "maxItems" not in tf.build_response_schema(TurnMode.REBUTTAL)["properties"]["premises"]["properties"]["explicit"]


def test_ledger_section_lists_only_learner_claims_not_old_premises():
    from app.opponent.turn_generators import Ledger

    ledger = Ledger(learner_claims=["Claim cũ."], ai_points=["Ý cũ."], attacked_premises=["Tiền đề đã đánh."])
    _, user = tf.build_full_prompt(TurnMode.REBUTTAL, _ctx(CON, 4, [_sp(3, CON, "x")], ledger))
    section = user.split("Các luận điểm người học đã nêu trước đó:\n")[1].split("\n\n")[0]
    assert section == "- Claim cũ."
    assert "explicit" not in user.split("Nhiệm vụ lượt này")[0]  # khong liet ke lai premises cu


async def test_no_new_speech_forces_empty_analysis_and_closing_target_null(client, db_session, fake_llm, fake_reviewer):
    ext = await _ready_session(client, fake_llm, fake_reviewer, "con")
    closing = json.loads(_out(TurnMode.CLOSING))
    closing.update(learner_claims=["Lặp lại claim cũ 1.", "Lặp lại claim cũ 2."], target_premise="lỡ điền",
                   premises={"explicit": ["E"], "implicit": ["I"]})
    fake_llm.responses = [_out(TurnMode.OPENING_REPLY), _out(TurnMode.REBUTTAL), json.dumps(closing, ensure_ascii=False)]
    assert (await _turn(client, ext, 2, [_learner(1)])).status_code == 201
    assert (await _turn(client, ext, 4, [_learner(3)])).status_code == 201
    assert (await _turn(client, ext, 5, [])).status_code == 201  # AI con luot 5: khong co bai learner moi

    call5 = _planner_calls(fake_llm)[2]
    assert tf.NO_NEW_SPEECH in call5["user"]
    assert call5["json_schema"] == tf.build_response_schema(TurnMode.CLOSING, has_new_speech=False)
    sid = await _session_id(db_session, ext)
    t5 = await db_session.scalar(select(OpponentTurn).where(OpponentTurn.session_id == sid, OpponentTurn.turn_index == 5))
    assert t5.learner_claims == [] and t5.premises == {"explicit": [], "implicit": []} and t5.target_premise is None
    row = next(r for r in await _calls(db_session, ext, LLMCallPurpose.TURN) if r.turn_id == t5.id)
    assert row.speech_checks["analysis_coerced"] == {"learner_claims": 2, "premises": 2}


def test_coerce_analysis_unit():
    out = tf.TurnOutput.model_validate(json.loads(_out(TurnMode.REBUTTAL)))
    assert tf.coerce_analysis(out, TurnMode.REBUTTAL, has_new_speech=True) == {}  # co bai moi: giu nguyen
    assert out.premises.explicit and out.target_premise
    out = tf.TurnOutput.model_validate(json.loads(_out(TurnMode.REBUTTAL)))
    out.target_premise = "x"
    assert tf.coerce_analysis(out, TurnMode.CLOSING, has_new_speech=True) == {"premises": 2}
    assert out.learner_claims and out.target_premise is None


@pytest.mark.parametrize("mode", [TurnMode.OPENING_FIRST, TurnMode.CLOSING])
def test_target_null_modes(mode):
    assert tf.build_response_schema(mode)["properties"]["target_premise"] == {"type": "null"}
    assert not tf.needs_target(mode)
    assert CASE["motion_reading"]  # dung chung fixture
