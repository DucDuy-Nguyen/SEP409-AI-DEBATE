"""
POST /opponent/sessions/{external_session_id}/turns — DB that (Postgres test), LLM gia (FakeLLMClient.generate_chat).
Bo sinh turn_baseline_v1 (GHIM qua fixture — mac dinh tu 3b la turn_full_v1): test o day cung la bang chung baseline
KHONG doi hanh vi. turn_full_v1: tests/test_turn_full.py.
"""
import json
import uuid

import pytest
from sqlalchemy import select, update

from app.core.config import Settings, get_settings
from app.main import app
from app.opponent.models import (
    LLMCallPurpose,
    OpponentLLMCall,
    OpponentSession,
    OpponentSpeech,
    OpponentTurn,
    SessionStatus,
)
from app.opponent.turn_generators import BASELINE_MAX_TOKENS
from tests.conftest import VALID_CASE_FILE, RateLimited

MOTION = "Nên cấm học sinh sử dụng điện thoại trong trường học"
ROUND = {1: "opening", 2: "opening", 3: "rebuttal", 4: "rebuttal", 5: "closing", 6: "closing"}
BASELINE_SETTINGS = Settings(_env_file=None, turn_generator_version="turn_baseline_v1")


@pytest.fixture(autouse=True)
def baseline_generator(client):
    """Chay SAU fixture client (client dat get_settings = TEST_SETTINGS)."""
    app.dependency_overrides[get_settings] = lambda: BASELINE_SETTINGS


async def _ready_session(client, fake_llm, fake_reviewer, ai_side: str) -> str:
    external_id = f"main-{uuid.uuid4()}"
    fake_llm.responses = [json.dumps(VALID_CASE_FILE, ensure_ascii=False)]
    fake_reviewer.default_position = "ung_ho_kien_nghi" if ai_side == "pro" else "phan_doi_kien_nghi"
    resp = await client.post(
        "/opponent/sessions",
        json={"external_session_id": external_id, "motion": MOTION, "ai_side": ai_side,
              "learner_side": "con" if ai_side == "pro" else "pro", "difficulty": "medium"},
    )
    assert resp.status_code == 201 and resp.json()["status"] == "ready", resp.text
    fake_llm.calls.clear()
    return external_id


def _learner(turn_index: int, text: str | None = None) -> dict:
    return {"turn_index": turn_index, "round_type": ROUND[turn_index], "text": text or f"Bài nói của learner lượt {turn_index}."}


async def _turn(client, external_id, turn_index, speeches=()):
    return await client.post(
        f"/opponent/sessions/{external_id}/turns",
        json={"turn_index": turn_index, "new_learner_speeches": list(speeches)},
    )


def _chat_calls(fake_llm) -> list[dict]:
    return [c for c in fake_llm.calls if c.get("chat")]


async def _session_id(db, external_id) -> uuid.UUID:
    return await db.scalar(select(OpponentSession.id).where(OpponentSession.external_session_id == external_id))


# ---------------- luong chinh ----------------


async def test_ai_pro_opening_first_then_rebuttal_then_closing_with_two_learner_speeches(client, db_session, fake_llm, fake_reviewer):
    ext = await _ready_session(client, fake_llm, fake_reviewer, "pro")
    fake_llm.responses = ["Mở màn của AI.", "Phản bác của AI.", "Tổng kết của AI."]
    fake_llm.usages = [{"tokens_in": 100, "tokens_out": 50}] * 3

    r1 = await _turn(client, ext, 1)
    assert r1.status_code == 201, r1.text
    assert r1.json() == {"turn_index": 1, "round_type": "opening", "mode": "opening_first", "speech_text": "Mở màn của AI."}
    first = _chat_calls(fake_llm)[0]
    assert first["messages"] == [{"role": "user", "content": "Mời bạn trình bày phần mở màn."}]
    assert first["temperature"] == 0.5 and first["max_tokens"] == BASELINE_MAX_TOKENS == 3000  # 3a, khong doc TURN_MAX_TOKENS

    r3 = await _turn(client, ext, 3, [_learner(2)])
    assert r3.status_code == 201 and r3.json()["mode"] == "rebuttal"

    # Luot 6: AI pro nhan 2 bai learner (4 rebuttal con, 5 closing con)
    r6 = await _turn(client, ext, 6, [_learner(4), _learner(5)])
    assert r6.status_code == 201, r6.text
    assert r6.json()["mode"] == "closing"
    assert _chat_calls(fake_llm)[2]["messages"] == [
        {"role": "user", "content": "Mời bạn trình bày phần mở màn."},
        {"role": "assistant", "content": "Mở màn của AI."},
        {"role": "user", "content": "Bài nói của learner lượt 2."},
        {"role": "assistant", "content": "Phản bác của AI."},
        {"role": "user", "content": "Bài nói của learner lượt 4."},
        {"role": "user", "content": "Bài nói của learner lượt 5."},
    ]

    sid = await _session_id(db_session, ext)
    speeches = (await db_session.scalars(select(OpponentSpeech).where(OpponentSpeech.session_id == sid)
                                         .order_by(OpponentSpeech.turn_index))).all()
    assert [(s.turn_index, s.speaker.value, s.round_type.value) for s in speeches] == [
        (1, "ai", "opening"), (2, "learner", "opening"), (3, "ai", "rebuttal"),
        (4, "learner", "rebuttal"), (5, "learner", "closing"), (6, "ai", "closing"),
    ]
    turns = (await db_session.scalars(select(OpponentTurn).where(OpponentTurn.session_id == sid)
                                      .order_by(OpponentTurn.turn_index))).all()
    assert [(t.turn_index, t.mode.value) for t in turns] == [(1, "opening_first"), (3, "rebuttal"), (6, "closing")]
    t6 = turns[-1]
    assert (t6.generator_version, t6.llm_model, t6.temperature) == ("turn_baseline_v1", "fake-model", 0.5)
    assert (t6.word_count, t6.tokens_in, t6.tokens_out) == (4, 100, 50)
    assert t6.learner_claims is None and t6.premises is None and t6.target_premise is None  # baseline de trong
    assert (await db_session.get(OpponentSpeech, t6.speech_id)).text == "Tổng kết của AI."


async def test_llm_calls_have_turn_id(client, db_session, fake_llm, fake_reviewer):
    ext = await _ready_session(client, fake_llm, fake_reviewer, "con")
    fake_llm.responses = ["Mở màn phe phản đối."]
    assert (await _turn(client, ext, 2, [_learner(1)])).status_code == 201

    sid = await _session_id(db_session, ext)
    turn = await db_session.scalar(select(OpponentTurn).where(OpponentTurn.session_id == sid))
    calls = (await db_session.scalars(select(OpponentLLMCall).where(
        OpponentLLMCall.session_id == sid, OpponentLLMCall.purpose == LLMCallPurpose.TURN))).all()
    assert len(calls) == 1 and calls[0].turn_id == turn.id and calls[0].success
    assert calls[0].prompt_version == "turn_baseline_v1"
    assert json.loads(calls[0].user_prompt) == [{"role": "user", "content": "Bài nói của learner lượt 1."}]
    assert calls[0].raw_output == "Mở màn phe phản đối."
    # Loi goi Case Planning khong gan turn_id
    others = (await db_session.scalars(select(OpponentLLMCall).where(
        OpponentLLMCall.session_id == sid, OpponentLLMCall.purpose != LLMCallPurpose.TURN))).all()
    assert others and all(c.turn_id is None for c in others)


async def test_baseline_prompt_does_not_contain_case_file(client, fake_llm, fake_reviewer):
    ext = await _ready_session(client, fake_llm, fake_reviewer, "con")
    fake_llm.responses = ["Mở màn."]
    await _turn(client, ext, 2, [_learner(1)])
    call = _chat_calls(fake_llm)[0]
    sent = call["system"] + json.dumps(call["messages"], ensure_ascii=False)
    for arg in VALID_CASE_FILE["arguments"]:
        assert arg["claim"] not in sent and arg["reasoning"] not in sent and arg["title"] not in sent
    assert VALID_CASE_FILE["weighing"] not in sent and VALID_CASE_FILE["motion_reading"] not in sent
    assert "Phản đối" in call["system"] and MOTION in call["system"]


async def test_ai_con_closing_turn_5_with_no_new_learner_speech(client, fake_llm, fake_reviewer):
    ext = await _ready_session(client, fake_llm, fake_reviewer, "con")
    fake_llm.responses = ["AI mở màn.", "AI phản bác.", "AI tổng kết."]
    assert (await _turn(client, ext, 2, [_learner(1)])).status_code == 201
    assert (await _turn(client, ext, 4, [_learner(3)])).status_code == 201

    r5 = await _turn(client, ext, 5, [])  # ngay sau luot 4 cua chinh AI: khong co bai learner moi
    assert r5.status_code == 201, r5.text
    assert r5.json()["mode"] == "closing" and r5.json()["speech_text"] == "AI tổng kết."
    messages = _chat_calls(fake_llm)[2]["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant", "user", "assistant", "user"]
    assert messages[-1]["content"] == "Mời bạn trình bày phần tổng kết."


# ---------------- validate ----------------


@pytest.mark.parametrize("ai_side,turn_index", [("pro", 2), ("pro", 4), ("con", 1), ("con", 6), ("con", 7), ("con", 0)])
async def test_turn_not_belonging_to_ai_is_400(client, fake_llm, fake_reviewer, ai_side, turn_index):
    ext = await _ready_session(client, fake_llm, fake_reviewer, ai_side)
    resp = await _turn(client, ext, turn_index)
    assert resp.status_code == 400, resp.text
    assert not _chat_calls(fake_llm)


@pytest.mark.parametrize(
    "speech,detail",
    [
        ({"turn_index": 1, "round_type": "rebuttal", "text": "x"}, "la opening"),  # sai round_type
        ({"turn_index": 2, "round_type": "opening", "text": "x"}, "luot cua AI"),  # luot cua AI (con)
        ({"turn_index": 5, "round_type": "closing", "text": "x"}, "luot cua AI"),
        ({"turn_index": 9, "round_type": "closing", "text": "x"}, "khong ton tai"),
    ],
)
async def test_learner_speech_not_matching_format_is_400(client, fake_llm, fake_reviewer, speech, detail):
    ext = await _ready_session(client, fake_llm, fake_reviewer, "con")
    resp = await _turn(client, ext, 2, [speech])
    assert resp.status_code == 400 and detail in resp.json()["detail"]


async def test_learner_speech_after_ai_turn_or_duplicate_is_400(client, fake_llm, fake_reviewer):
    ext = await _ready_session(client, fake_llm, fake_reviewer, "pro")
    fake_llm.responses = ["AI mở màn."]
    await _turn(client, ext, 1)
    later = await _turn(client, ext, 3, [_learner(2), _learner(4)])
    assert later.status_code == 400 and "khong nam truoc" in later.json()["detail"]
    dup = await _turn(client, ext, 3, [_learner(2), _learner(2)])
    assert dup.status_code == 400 and "2 lan" in dup.json()["detail"]


async def test_blank_learner_speech_is_422(client, fake_llm, fake_reviewer):
    ext = await _ready_session(client, fake_llm, fake_reviewer, "con")
    assert (await _turn(client, ext, 2, [_learner(1, "   ")])).status_code == 422


async def test_missing_previous_turn_is_409(client, db_session, fake_llm, fake_reviewer):
    ext = await _ready_session(client, fake_llm, fake_reviewer, "con")
    # Luot 4 khi chua co luot 1-3
    resp = await _turn(client, ext, 4, [_learner(3)])
    assert resp.status_code == 409 and "[1, 2]" in resp.json()["detail"]
    # Luot 4 khi co 1, 2 nhung thieu bai learner luot 3
    fake_llm.responses = ["AI mở màn."]
    await _turn(client, ext, 2, [_learner(1)])
    resp = await _turn(client, ext, 4, [])
    assert resp.status_code == 409 and "[3]" in resp.json()["detail"]
    assert len(_chat_calls(fake_llm)) == 1
    sid = await _session_id(db_session, ext)
    assert await db_session.scalar(select(OpponentSpeech).where(OpponentSpeech.session_id == sid,
                                                               OpponentSpeech.turn_index == 3)) is None


async def test_session_not_ready_is_409_and_unknown_is_404(client, db_session, fake_llm, fake_reviewer):
    ext = await _ready_session(client, fake_llm, fake_reviewer, "con")
    await db_session.execute(update(OpponentSession).where(OpponentSession.external_session_id == ext)
                             .values(status=SessionStatus.FAILED))
    resp = await _turn(client, ext, 2, [_learner(1)])
    assert resp.status_code == 409 and "failed" in resp.json()["detail"]
    assert (await _turn(client, "khong-ton-tai", 2, [_learner(1)])).status_code == 404


# ---------------- idempotent / snapshot ----------------


async def test_idempotent_same_request_returns_200_without_llm(client, fake_llm, fake_reviewer):
    ext = await _ready_session(client, fake_llm, fake_reviewer, "con")
    fake_llm.responses = ["AI mở màn."]
    first = await _turn(client, ext, 2, [_learner(1)])
    assert first.status_code == 201

    again = await _turn(client, ext, 2, [_learner(1)])
    assert again.status_code == 200 and again.json() == first.json()
    assert len(_chat_calls(fake_llm)) == 1  # khong goi LLM lan 2
    # Gui lai khong kem bai learner cung khop (moi bai gui kem deu da luu)
    assert (await _turn(client, ext, 2, [])).status_code == 200


async def test_idempotent_with_different_learner_speech_is_409(client, fake_llm, fake_reviewer):
    ext = await _ready_session(client, fake_llm, fake_reviewer, "con")
    fake_llm.responses = ["AI mở màn."]
    await _turn(client, ext, 2, [_learner(1)])
    resp = await _turn(client, ext, 2, [_learner(1, "Một bài nói khác hẳn.")])
    assert resp.status_code == 409 and "khac" in resp.json()["detail"]
    assert len(_chat_calls(fake_llm)) == 1


async def test_resending_stored_learner_speech_with_other_text_is_409(client, fake_llm, fake_reviewer):
    ext = await _ready_session(client, fake_llm, fake_reviewer, "pro")
    fake_llm.responses = ["AI mở màn.", "AI phản bác.", "AI tổng kết."]
    await _turn(client, ext, 1)
    await _turn(client, ext, 3, [_learner(2)])
    conflict = await _turn(client, ext, 6, [_learner(2, "Sửa lại bài lượt 2."), _learner(4), _learner(5)])
    assert conflict.status_code == 409 and "[2]" in conflict.json()["detail"]
    assert len(_chat_calls(fake_llm)) == 2  # khong goi LLM, khong luu bai 4, 5
    ok = await _turn(client, ext, 6, [_learner(2), _learner(4), _learner(5)])  # gui lai bai 2 y het: chap nhan
    assert ok.status_code == 201, ok.text


# ---------------- sinh that bai ----------------


async def test_empty_output_retried_then_success(client, db_session, fake_llm, fake_reviewer):
    ext = await _ready_session(client, fake_llm, fake_reviewer, "con")
    fake_llm.responses = ["   ", "AI mở màn."]
    resp = await _turn(client, ext, 2, [_learner(1)])
    assert resp.status_code == 201 and resp.json()["speech_text"] == "AI mở màn."
    sid = await _session_id(db_session, ext)
    calls = (await db_session.scalars(select(OpponentLLMCall).where(
        OpponentLLMCall.session_id == sid, OpponentLLMCall.purpose == LLMCallPurpose.TURN)
        .order_by(OpponentLLMCall.attempt))).all()
    assert [(c.attempt, c.success, c.failure_kind) for c in calls] == [(1, False, "empty_output"), (2, True, None)]
    assert calls[0].turn_id == calls[1].turn_id is not None


async def test_empty_output_every_time_is_502_and_calls_logged(client, db_session, fake_llm, fake_reviewer):
    ext = await _ready_session(client, fake_llm, fake_reviewer, "con")
    fake_llm.responses = ["", "  "]
    resp = await _turn(client, ext, 2, [_learner(1)])
    assert resp.status_code == 502
    sid = await _session_id(db_session, ext)
    calls = (await db_session.scalars(select(OpponentLLMCall).where(
        OpponentLLMCall.session_id == sid, OpponentLLMCall.purpose == LLMCallPurpose.TURN))).all()
    assert len(calls) == 2 and all(c.turn_id is None and c.failure_kind == "empty_output" for c in calls)
    assert await db_session.scalar(select(OpponentTurn).where(OpponentTurn.session_id == sid)) is None
    # Bai learner da luu -> goi lai (khong can gui lai bai 1) sinh duoc
    fake_llm.responses = ["AI mở màn."]
    assert (await _turn(client, ext, 2, [])).status_code == 201


async def test_rate_limit_waits_then_succeeds(client, db_session, fake_llm, fake_reviewer):
    ext = await _ready_session(client, fake_llm, fake_reviewer, "con")
    fake_llm.responses = [RateLimited("Please try again in 0.01s."), "AI mở màn."]
    resp = await _turn(client, ext, 2, [_learner(1)])
    assert resp.status_code == 201
    sid = await _session_id(db_session, ext)
    calls = (await db_session.scalars(select(OpponentLLMCall).where(
        OpponentLLMCall.session_id == sid, OpponentLLMCall.purpose == LLMCallPurpose.TURN)
        .order_by(OpponentLLMCall.attempt))).all()
    assert [c.failure_kind for c in calls] == ["rate_limited", None]
    assert calls[0].rate_limit_wait_ms == 10


async def test_provider_error_is_502(client, fake_llm, fake_reviewer):
    ext = await _ready_session(client, fake_llm, fake_reviewer, "con")
    fake_llm.responses = [RuntimeError("503 groq down")]
    resp = await _turn(client, ext, 2, [_learner(1)])
    assert resp.status_code == 502 and "groq down" in resp.json()["detail"]


async def test_budget_exceeded_is_504(client, db_session, fake_llm, fake_reviewer):
    ext = await _ready_session(client, fake_llm, fake_reviewer, "con")
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, turn_generator_version="turn_baseline_v1", turn_total_budget_seconds=0.2
    )
    fake_llm.responses = ["AI mở màn."]
    fake_llm.delay_seconds = 1.0
    resp = await _turn(client, ext, 2, [_learner(1)])
    assert resp.status_code == 504
    sid = await _session_id(db_session, ext)
    call = await db_session.scalar(select(OpponentLLMCall).where(
        OpponentLLMCall.session_id == sid, OpponentLLMCall.purpose == LLMCallPurpose.TURN))
    assert call.failure_kind == "budget_exceeded" and call.turn_id is None
