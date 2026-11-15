"""
turn_full_v4_stream + POST /opponent/sessions/{id}/turns/stream: prompt / parse / tach bai noi khi stream, va API SSE
(DB that, LLM gia FakeLLMClient.generate_stream day tung doan 9 ky tu).
"""
import json

import pytest
from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.main import app
from app.opponent import turn_full as tf
from app.opponent.match_format import TurnMode
from app.opponent.models import OpponentLLMCall, OpponentTurn
from app.opponent.turn_generators import FULL_V4_STREAM, TurnFailure
from tests.test_turn_full import TARGET, _ctx, _out, _words
from tests.test_turns_api import _learner, _ready_session, _session_id



def _stream_out(mode: TurnMode, speech: str | None = None, n_words: int | None = None) -> str:
    """Output dung dinh dang v4: JSON 4 truong phan tich -> dong phan cach -> bai noi van ban thuan."""
    data = json.loads(_out(mode, n_words=n_words, speech=speech))
    text = data.pop("speech_text")
    return f"{json.dumps(data, ensure_ascii=False)}\n{tf.SPEECH_DELIMITER}\n{text}"


def _events(body: str) -> list[dict]:
    out = []
    for block in body.split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.strip().splitlines() if ": " in line)
        if "data" in lines:
            event = json.loads(lines["data"])
            assert event["type"] == lines["event"]
            out.append(event)
    return out


async def _stream(client, ext, turn_index, speeches=()):
    return await client.post(
        f"/opponent/sessions/{ext}/turns/stream", json={"turn_index": turn_index, "new_learner_speeches": list(speeches)}
    )


# ---------------- prompt / parse / extractor ----------------


def test_stream_prompt_is_v3_with_the_speech_after_a_delimiter_line():
    from app.opponent.models import DebateSide

    ctx = _ctx(DebateSide.PRO, 1)
    system, user = tf.build_stream_prompt(TurnMode.OPENING_FIRST, ctx)
    v3_system, v3_user = tf.build_full_prompt(TurnMode.OPENING_FIRST, ctx, None, tf.FULL_V3)

    assert system == v3_system
    assert f"2. Một dòng chỉ gồm {tf.SPEECH_DELIMITER}" in user
    assert "Chỉ trả về JSON hợp lệ." not in user and "- speech_text: bài nói hoàn chỉnh" not in user
    assert "- Độ dài bài nói (speech_text): từ 320 đến 480 từ." in user
    # Phan con lai cua prompt (case, rang buoc) giu nguyen v3
    assert v3_user.split("Nhiệm vụ lượt này")[0] == user.split("Nhiệm vụ lượt này")[0]


def test_parse_stream_output_accepts_the_v3_style_too_and_reports_a_missing_delimiter():
    out = tf.parse_stream_output(_stream_out(TurnMode.OPENING_FIRST), TurnMode.OPENING_FIRST, 400)
    assert out.speech_text == _words(400) and len(out.ai_points) == 2

    # Model quen dinh dang moi, viet speech_text trong JSON nhu v3: van nhan
    v3 = tf.parse_stream_output(_out(TurnMode.OPENING_FIRST), TurnMode.OPENING_FIRST, 400)
    assert v3.speech_text == _words(400)

    head = json.dumps({"learner_claims": [], "premises": {"explicit": [], "implicit": []}, "target_premise": None,
                       "ai_points": ["a", "b"]})
    with pytest.raises(tf._Invalid) as e:
        tf.parse_stream_output(head + "\nBài nói không có dòng phân cách.", TurnMode.OPENING_FIRST, 400)
    assert e.value.kind == TurnFailure.INVALID_JSON and e.value.issues == [tf.MISSING_DELIMITER_ISSUE]


def test_extractor_emits_only_the_speech_even_when_the_delimiter_is_split():
    ex = tf.SpeechStreamExtractor()
    pieces = ['{"ai_points": ["a"]}\n===BÀI', " NÓI===", "\n  Xin ", "chào", " bạn."]
    assert "".join(ex.feed(p) for p in pieces) == "Xin chào bạn."
    # Khong co dong phan cach: khong day gi
    assert tf.SpeechStreamExtractor().feed('{"speech_text": "Xin chào"}') == ""


# ---------------- API ----------------


async def test_stream_sends_the_speech_in_pieces_then_the_stored_turn(client, db_session, fake_llm, fake_reviewer):
    ext = await _ready_session(client, fake_llm, fake_reviewer, "pro")
    fake_llm.responses = [_stream_out(TurnMode.OPENING_FIRST)]

    resp = await _stream(client, ext, 1)

    assert resp.status_code == 200 and resp.headers["content-type"].startswith("text/event-stream")
    events = _events(resp.text)
    assert events[0] == {"type": "attempt", "attempt": 1, "previous_failure": None}
    deltas = [e["text"] for e in events if e["type"] == "delta"]
    assert len(deltas) > 10 and "".join(deltas) == _words(TARGET[TurnMode.OPENING_FIRST])
    assert events[-1] == {"type": "done", "status": 201, "turn": {
        "turn_index": 1, "round_type": "opening", "mode": "opening_first", "speech_text": "".join(deltas)}}

    call = [c for c in fake_llm.calls if c.get("stream")][0]
    assert call["reasoning_effort"] == "medium" and call["max_tokens"] == 6000
    sid = await _session_id(db_session, ext)
    turn = await db_session.scalar(select(OpponentTurn).where(OpponentTurn.session_id == sid))
    assert turn.generator_version == FULL_V4_STREAM and len(turn.ai_points) == 2
    logged = (await db_session.scalars(select(OpponentLLMCall).where(OpponentLLMCall.turn_id == turn.id))).all()
    assert {c.prompt_version for c in logged if c.purpose.value == "turn"} == {FULL_V4_STREAM}


async def test_a_rejected_attempt_is_replaced_by_the_next_one(client, fake_llm, fake_reviewer):
    ext = await _ready_session(client, fake_llm, fake_reviewer, "pro")
    bad = _words(390) + " Nhiều nghiên cứu cho thấy học sinh mất tập trung."  # bang chung mo ho HIGH -> thu lai
    fake_llm.responses = [_stream_out(TurnMode.OPENING_FIRST, speech=bad), _stream_out(TurnMode.OPENING_FIRST)]

    events = _events((await _stream(client, ext, 1)).text)

    attempts = [i for i, e in enumerate(events) if e["type"] == "attempt"]
    assert [events[i]["attempt"] for i in attempts] == [1, 2]
    assert events[attempts[1]]["previous_failure"] == TurnFailure.BANNED_PHRASE
    first = "".join(e["text"] for e in events[attempts[0]:attempts[1]] if e["type"] == "delta")
    second = "".join(e["text"] for e in events[attempts[1]:] if e["type"] == "delta")
    assert first == bad and second == _words(400)
    assert events[-1]["type"] == "done" and events[-1]["turn"]["speech_text"] == second
    # Lan sinh 2 co phan hoi sua loi, van dung prompt v4
    assert tf.SPEECH_DELIMITER in [c for c in fake_llm.calls if c.get("stream")][1]["user"]


async def test_failure_after_streaming_started_is_an_error_event(client, fake_llm, fake_reviewer):
    ext = await _ready_session(client, fake_llm, fake_reviewer, "pro")
    bad = _words(390) + " Nhiều nghiên cứu cho thấy học sinh mất tập trung."
    fake_llm.responses = [_stream_out(TurnMode.OPENING_FIRST, speech=bad)] * 3

    events = _events((await _stream(client, ext, 1)).text)

    assert events[-1]["type"] == "error" and events[-1]["status"] == 502
    assert events[-1]["detail"].startswith("AI tra ve bai noi khong hop le")


async def test_errors_before_generating_and_replays_are_plain_json(client, fake_llm, fake_reviewer):
    missing = await _stream(client, "khong-co", 1)
    assert missing.status_code == 404 and missing.json() == {"detail": "Khong tim thay session khong-co"}

    ext = await _ready_session(client, fake_llm, fake_reviewer, "con")
    not_ai = await _stream(client, ext, 1)  # ai_side=con: luot 1 la cua learner
    assert not_ai.status_code == 400

    fake_llm.responses = [_stream_out(TurnMode.OPENING_REPLY)]
    first = _events((await _stream(client, ext, 2, [_learner(1)])).text)[-1]
    again = await _stream(client, ext, 2, [_learner(1)])  # cung request: luot da co, khong goi LLM
    assert again.status_code == 200 and again.headers["content-type"].startswith("application/json")
    assert again.json() == first["turn"] and not fake_llm.responses


async def test_stream_reasoning_effort_is_its_own_setting(client, fake_llm, fake_reviewer):
    ext = await _ready_session(client, fake_llm, fake_reviewer, "pro")
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, turn_stream_reasoning_effort="low")
    fake_llm.responses = [_stream_out(TurnMode.OPENING_FIRST)]

    assert _events((await _stream(client, ext, 1)).text)[-1]["type"] == "done"
    assert [c for c in fake_llm.calls if c.get("stream")][0]["reasoning_effort"] == "low"


def test_extractor_keeps_a_combining_mark_split_across_pieces():
    # "à" gui dang tach dau (a + U+0300), dau roi sang doan sau: khong duoc mat dau, khong lech vi tri da gui
    ex = tf.SpeechStreamExtractor()
    pieces = ["{}\n===BÀI NÓI===\nVa", "̀ tie", "p theo."]
    assert "".join(ex.feed(p) for p in pieces) == "Và tiep theo."


class ReadError(Exception):
    """Cung ten lop voi httpx.ReadError -> is_transient_error() nhan la loi mang, _call thu lai."""


async def test_network_drop_mid_stream_restarts_the_text_of_that_attempt(client, fake_llm, fake_reviewer):
    from tests.conftest import PartialThenError

    ext = await _ready_session(client, fake_llm, fake_reviewer, "pro")
    full = _stream_out(TurnMode.OPENING_FIRST)
    cut = full.index(tf.SPEECH_DELIMITER) + len(tf.SPEECH_DELIMITER) + 30
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, llm_transient_retry_wait_seconds=0)
    fake_llm.responses = [PartialThenError(full[:cut], ReadError("mat mang")), full]

    events = _events((await _stream(client, ext, 1)).text)

    restarts = [i for i, e in enumerate(events) if e["type"] == "attempt"]
    assert [events[i]["attempt"] for i in restarts] == [1, None]
    assert events[restarts[1]]["previous_failure"] == TurnFailure.TRANSIENT_ERROR
    after = "".join(e["text"] for e in events[restarts[1]:] if e["type"] == "delta")
    assert after == events[-1]["turn"]["speech_text"] == _words(400)


def test_groq_generate_stream_sends_only_content_and_keeps_usage():
    from types import SimpleNamespace as NS

    from app.llm.client import GroqClient

    chunks = [
        NS(usage=None, choices=[NS(delta=NS(content=None, reasoning="suy luận..."), finish_reason=None)]),
        NS(usage=None, choices=[NS(delta=NS(content="Xin "), finish_reason=None)]),
        NS(usage=None, choices=[NS(delta=NS(content="chào."), finish_reason="stop")]),
        NS(usage=NS(prompt_tokens=10, completion_tokens=50, completion_tokens_details=NS(reasoning_tokens=40)), choices=[]),
    ]
    sent = {}

    def create(**kwargs):
        sent.update(kwargs)
        return iter(chunks)

    groq = GroqClient.__new__(GroqClient)
    groq._client = NS(chat=NS(completions=NS(create=create)))
    groq.model, groq._temperature, groq._max_tokens = "m", 0.2, 100
    pieces: list[str] = []

    out = groq.generate_stream("sys", "user", pieces.append, reasoning_effort="low")

    assert out == "Xin chào." and pieces == ["Xin ", "chào."]
    assert sent["stream"] is True and "response_format" not in sent and sent["reasoning_effort"] == "low"
    assert groq.last_finish_reason == "stop"
    assert groq.last_usage["tokens_out"] == 50 and groq.last_usage["reasoning_tokens"] == 40
