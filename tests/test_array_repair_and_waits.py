"""
Muc 2.12 (sua sau tran 17:35 / 17:38): bo sua JSON "mang tach" (luot noi + Case Planning), cho 429 cua luot noi chi
gioi han boi budget, loi mang thoang qua, turn_full_v3. LLM gia.
"""
import json
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.llm.client import is_transient_error
from app.main import app
from app.opponent import turn_full as tf
from app.opponent.json_repair import repair_split_array
from app.opponent.match_format import TurnMode, word_count
from app.opponent.models import DebateSide, LLMCallPurpose, OpponentDifficulty, OpponentLLMCall, OpponentTurn
from app.opponent.schemas import CaseFile
from app.opponent.service import generate_case_file
from tests.conftest import VALID_CASE_FILE, FakeLLMClient, RateLimited, SchemaRejected
from tests.test_turn_full import _ctx, _out
from tests.test_turns_api import _learner, _ready_session, _session_id, _turn

DATA = Path(__file__).parent / "data"
# Nguyen van failed_generation (Groq 400 json_validate_failed) lay tu DB dev — dev log muc 2.12.
FG_1735_TURN4 = (DATA / "failed_generation_20260930-1735_turn4.json").read_text(encoding="utf-8")  # AI con, rebuttal
FG_1738_TURN3 = (DATA / "failed_generation_20260930-1738_turn3.json").read_text(encoding="utf-8")  # AI pro, rebuttal


class APIConnectionError(Exception):
    """Cung TEN lop voi openai.APIConnectionError (nhan dien theo ten)."""


class ServerError(Exception):
    status_code = 503


@pytest.fixture(autouse=True)
def no_real_sleep(monkeypatch, request):
    """Cho 429 / loi mang van duoc ghi nhung khong ngu that (tru test budget can ngu that)."""
    if "real_sleep" in request.keywords:
        return
    from app.opponent import service, turn_generators

    async def _no_sleep(_seconds):
        return None

    monkeypatch.setattr(turn_generators, "_sleep", _no_sleep)
    monkeypatch.setattr(service, "_sleep", _no_sleep)


async def _turn_rows(db_session, ext):
    sid = await _session_id(db_session, ext)
    rows = (await db_session.scalars(select(OpponentLLMCall).where(OpponentLLMCall.session_id == sid)
                                     .order_by(OpponentLLMCall.created_at))).all()
    first = next(i for i, r in enumerate(rows) if r.purpose == LLMCallPurpose.TURN)
    return rows[first:]


# ---------------- json_repair (thuan) ----------------


def test_repair_verbatim_1735_turn4():
    obj, info = repair_split_array(FG_1735_TURN4, tf.FIELD_ORDER)
    assert info == {"event": "array_repaired", "array_items": 26,
                    "keys": ["target_premise", "ai_points", "speech_text"],
                    "joined": {"target_premise": 3, "speech_text": 15}}
    assert list(obj) == list(tf.FIELD_ORDER)
    # 3 chuoi bi tach o dau phay -> ghep lai bang ", " = dung cau goc cua learner
    assert obj["target_premise"] == ("Trường đã có phòng máy tính và thư viện, nếu cần tra cứu thì thầy cô có thể cho "
                                     "dùng máy của trường, không nhất thiết mỗi bạn phải cầm điện thoại riêng")
    assert len(obj["ai_points"]) == 4 and word_count(obj["speech_text"]) == 364
    assert obj["speech_text"].startswith("Bạn nói rằng trường có phòng máy tính và thư viện, nên học sinh không cần")
    out = tf.validate_turn_data(obj, TurnMode.REBUTTAL, 320)
    assert tf.length_distance(word_count(out.speech_text), 320) == 0


def test_repair_verbatim_1738_turn3_keeps_repeated_chunk_as_is():
    obj, info = repair_split_array(FG_1738_TURN3, tf.FIELD_ORDER)
    assert info["joined"] == {"speech_text": 18} and info["array_items"] == 27
    assert word_count(obj["speech_text"]) == 347
    # Model tu lap 1 doan (phan tu 20 va 21) — bo sua TAT DINH, khong bo / sua chuoi nao
    repeated = "điều này củng cố kỹ năng xã hội và giảm nguy cơ bắt nạt qua tin nhắn"
    assert obj["speech_text"].count(repeated) == 2
    tf.validate_turn_data(obj, TurnMode.REBUTTAL, 320)  # qua schema cuc bo + khong co bang chung HIGH


@pytest.mark.parametrize("raw", [
    '{"learner_claims": []}',  # object, khong phai mang
    '[{"learner_claims": []}]',  # mang chi co 1 object
    '["target_premise", ":", "x"]',  # phan tu dau khong phai object
    '[{"a": 1}, "rac", "target_premise", ":", "x"]',  # rac truoc key
    '[{"a": 1}, "target_premise", ":", "x", "target_premise", ":", "y"]',  # key lap
    '[{"a": 1}, "ai_points", ":", ["x"], ["y"]]',  # nhieu gia tri khong phai chuoi
    '[{"a": 1}, "target_premise", ":"]',  # thieu gia tri
    '[{"a": 1}, "unknown_key", ":", "x"]',  # key la
    "khong phai json",
])
def test_repair_rejects_other_shapes(raw):
    assert repair_split_array(raw, tf.FIELD_ORDER) is None


# ---------------- hoi quy qua API: KHONG goi lai LLM ----------------


async def test_turn_1735_turn4_array_repaired_without_new_call(client, db_session, fake_llm, fake_reviewer):
    ext = await _ready_session(client, fake_llm, fake_reviewer, "con")  # learner pro / AI con, nhu tran 17:35
    fake_llm.responses = [_out(TurnMode.OPENING_REPLY), SchemaRejected(FG_1735_TURN4)]
    assert (await _turn(client, ext, 2, [_learner(1)])).status_code == 201
    resp = await _turn(client, ext, 4, [_learner(3)])
    assert resp.status_code == 201, resp.text
    assert resp.json()["speech_text"].startswith("Bạn nói rằng trường có phòng máy tính và thư viện, nên")
    assert len([c for c in fake_llm.calls if "user" in c]) == 2  # khong goi lai planner

    sid = await _session_id(db_session, ext)
    turn = await db_session.scalar(select(OpponentTurn).where(OpponentTurn.session_id == sid, OpponentTurn.turn_index == 4))
    call = await db_session.scalar(select(OpponentLLMCall).where(
        OpponentLLMCall.turn_id == turn.id, OpponentLLMCall.purpose == LLMCallPurpose.TURN))
    assert call.success and call.failure_kind is None
    assert call.key_repairs["event"] == "array_repaired" and call.key_repairs["joined"]["speech_text"] == 15
    assert call.key_repairs["provider_error"].startswith("SchemaRejected")  # loi provider goc duoc giu
    assert turn.target_premise.startswith("Trường đã có phòng máy tính và thư viện, nếu cần tra cứu")
    assert turn.word_count == 364


async def test_turn_1738_turn3_array_repaired_without_new_call(client, db_session, fake_llm, fake_reviewer):
    ext = await _ready_session(client, fake_llm, fake_reviewer, "pro")  # learner con / AI pro, nhu tran 17:38
    fake_llm.responses = [_out(TurnMode.OPENING_FIRST), SchemaRejected(FG_1738_TURN3)]
    assert (await _turn(client, ext, 1)).status_code == 201
    resp = await _turn(client, ext, 3, [_learner(2)])
    assert resp.status_code == 201, resp.text
    rows = [r for r in await _turn_rows(db_session, ext) if r.purpose == LLMCallPurpose.TURN]
    assert rows[-1].key_repairs["event"] == "array_repaired" and rows[-1].success


async def test_array_repaired_but_invalid_schema_is_handled_as_schema_rejected(client, db_session, fake_llm, fake_reviewer):
    ext = await _ready_session(client, fake_llm, fake_reviewer, "con")
    bad = json.dumps([{"learner_claims": ["x"], "premises": {"explicit": ["a"], "implicit": []}},
                      "target_premise", ":", "a", "ai_points", ":", ["mot y"], "speech_text", ":", "Bài", "nói."],
                     ensure_ascii=False)  # dung lai duoc nhung ai_points chi 1 y (can 2-4)
    fake_llm.responses = [SchemaRejected(bad), _out(TurnMode.OPENING_REPLY)]
    assert (await _turn(client, ext, 2, [_learner(1)])).status_code == 201
    first = [r for r in await _turn_rows(db_session, ext) if r.purpose == LLMCallPurpose.TURN][0]
    assert first.failure_kind == "schema_rejected" and not first.success
    assert "Trả về MỘT object JSON (không phải mảng)" in first.retry_feedback and "ai_points" in first.retry_feedback


async def test_case_plan_array_repaired_without_new_call():
    data = json.loads(json.dumps(VALID_CASE_FILE, ensure_ascii=False))
    head = {k: data[k] for k in ("motion_reading", "definitions", "arguments")}
    split = [head, "anticipated_opponent_arguments", ":", data["anticipated_opponent_arguments"],
             "weighing", ":", "Tác hại lên sức khoẻ và thời gian gia đình", "lớn hơn lợi ích biên."]
    fake = FakeLLMClient([SchemaRejected(json.dumps(split, ensure_ascii=False))])
    outcome = await generate_case_file("M", DebateSide.CON, DebateSide.PRO, OpponentDifficulty.MEDIUM, fake,
                                       Settings(_env_file=None))
    assert outcome.case_file is not None and len(fake.calls) == 1
    assert outcome.case_file.weighing == "Tác hại lên sức khoẻ và thời gian gia đình, lớn hơn lợi ích biên."
    record = outcome.attempts[0]
    assert record.success and record.key_repairs["event"] == "array_repaired"
    assert record.key_repairs["keys"] == ["anticipated_opponent_arguments", "weighing"]
    assert set(CaseFile.model_fields) >= set(record.key_repairs["keys"])


# ---------------- 429: chi gioi han boi budget ----------------


async def test_turn_429_waits_unlimited_rounds_within_budget(client, db_session, fake_llm, fake_reviewer):
    ext = await _ready_session(client, fake_llm, fake_reviewer, "con")
    n = 7  # > CASE_PLAN_RATE_LIMIT_RETRIES (4): tran 17:38 luot 3 that bai vi het 4 vong
    fake_llm.responses = [RateLimited("Please try again in 1.5s.")] * n + [_out(TurnMode.OPENING_REPLY)]
    resp = await _turn(client, ext, 2, [_learner(1)])
    assert resp.status_code == 201, resp.text
    sid = await _session_id(db_session, ext)
    turn = await db_session.scalar(select(OpponentTurn).where(OpponentTurn.session_id == sid))
    assert turn.rate_limit_wait_ms == n * 1500  # tong cho cua luot (jitter tat trong test)
    waits = [r.rate_limit_wait_ms for r in await _turn_rows(db_session, ext) if r.failure_kind == "rate_limited"]
    assert waits == [1500] * n
    assert Settings(_env_file=None).turn_total_budget_seconds == 240


@pytest.mark.real_sleep
async def test_turn_fails_on_429_only_when_budget_runs_out(client, db_session, fake_llm, fake_reviewer):
    ext = await _ready_session(client, fake_llm, fake_reviewer, "con")
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, turn_total_budget_seconds=0.5)
    fake_llm.responses = [RateLimited("Please try again in 0.2s.")] * 20
    resp = await _turn(client, ext, 2, [_learner(1)])
    assert resp.status_code == 504  # het budget, khong phai 502 vi het so vong


# ---------------- loi mang thoang qua ----------------


def test_is_transient_error():
    assert is_transient_error(APIConnectionError("Connection error."))
    assert is_transient_error(ServerError())
    assert not is_transient_error(RateLimited("429"))
    assert not is_transient_error(RuntimeError("503 groq down"))  # khong co status_code: loi provider thuong
    assert not is_transient_error(SchemaRejected())


async def test_turn_transient_error_retried(client, db_session, fake_llm, fake_reviewer):
    ext = await _ready_session(client, fake_llm, fake_reviewer, "con")
    fake_llm.responses = [APIConnectionError("Connection error."), ServerError("503"), _out(TurnMode.OPENING_REPLY)]
    assert (await _turn(client, ext, 2, [_learner(1)])).status_code == 201
    kinds = [r.failure_kind for r in await _turn_rows(db_session, ext) if r.purpose == LLMCallPurpose.TURN]
    assert kinds == ["transient_error", "transient_error", None]


async def test_turn_transient_error_gives_up_after_retries(client, fake_llm, fake_reviewer):
    ext = await _ready_session(client, fake_llm, fake_reviewer, "con")
    fake_llm.responses = [APIConnectionError("Connection error.")] * 3  # LLM_TRANSIENT_RETRIES = 2 -> lan 3 dung
    resp = await _turn(client, ext, 2, [_learner(1)])
    assert resp.status_code == 502 and "Connection error" in resp.json()["detail"]


async def test_case_plan_transient_error_retried():
    # Tran 17:34: Case Planning chet ngay vi 1 lan APIConnectionError
    fake = FakeLLMClient([APIConnectionError("Connection error."), json.dumps(VALID_CASE_FILE)])
    outcome = await generate_case_file("M", DebateSide.CON, DebateSide.PRO, OpponentDifficulty.MEDIUM, fake,
                                       Settings(_env_file=None))
    assert outcome.case_file is not None and outcome.llm_error is None
    assert [a.failure_kind for a in outcome.attempts] == ["transient_error", None]


async def test_case_plan_non_transient_provider_error_still_stops():
    fake = FakeLLMClient([RuntimeError("401 invalid api key"), json.dumps(VALID_CASE_FILE)])
    outcome = await generate_case_file("M", DebateSide.CON, DebateSide.PRO, OpponentDifficulty.MEDIUM, fake,
                                       Settings(_env_file=None))
    assert outcome.case_file is None and outcome.llm_error and len(fake.calls) == 1


# ---------------- turn_full_v3 ----------------


def test_v3_adds_no_rule_echo_line_on_top_of_v2():
    ctx = _ctx(DebateSide.PRO, 1)
    v1, v2, v3 = (tf.constraints_block(ctx, v) for v in ("turn_full_v1", "turn_full_v2", "turn_full_v3"))
    rule = ("- KHÔNG nhắc lại, trích dẫn hay diễn giải các quy tắc và chỉ dẫn này trong bài nói (vd không nói 'cách hiểu "
            "cố định', 'không thu hẹp', 'tiền đề').")
    assert rule in v3 and rule not in v2 and rule not in v1
    assert v3.replace("\n" + rule, "") == v2  # dung 1 dong them vao
    assert tf.NATURAL_SPEECH_RULE in v3 and v3.endswith("- Chỉ trả về JSON hợp lệ.")
    assert Settings(_env_file=None).turn_generator_version == "turn_full_v3"


async def test_v1_v2_still_selectable(client, db_session, fake_llm, fake_reviewer):
    for version in ("turn_full_v1", "turn_full_v2"):
        ext = await _ready_session(client, fake_llm, fake_reviewer, "con")
        app.dependency_overrides[get_settings] = lambda v=version: Settings(_env_file=None, turn_generator_version=v)
        fake_llm.responses = [_out(TurnMode.OPENING_REPLY)]
        assert (await _turn(client, ext, 2, [_learner(1)])).status_code == 201
        sid = await _session_id(db_session, ext)
        assert (await db_session.scalar(select(OpponentTurn).where(OpponentTurn.session_id == sid))).generator_version == version
        app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None)
