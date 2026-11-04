"""
Muc 2.17: mac dinh case_plan_v7 (co burden) / v5 (khong burden); turn_full_v4 = v3 + ganh nang chung minh cua phe AI
(system prompt + khoi rang buoc), co co TURN_BURDEN_ENABLED de tat (ablation); try_match + fixture M01 co burden. LLM gia.
"""
import json
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.main import app
from app.opponent import turn_full as tf
from app.opponent.match_format import TurnMode
from app.opponent.models import (
    DebateSide,
    LLMCallPurpose,
    OpponentCaseFile,
    OpponentDifficulty,
    OpponentLLMCall,
    OpponentSession,
    OpponentTurn,
)
from scripts import try_match as tm
from tests.conftest import VALID_CASE_FILE, FakeLLMClient, FakeStanceReviewer
from tests.test_turn_full import _ctx, _out, _sp
from tests.test_turns_api import _learner, _session_id, _turn

ROOT = Path(__file__).resolve().parent.parent
P1 = next(m for m in json.loads((ROOT / "experiments" / "motions_v3.json").read_text(encoding="utf-8"))["motions"]
          if m["id"] == "P1")
BP, BC = P1["burden_pro"], P1["burden_con"]
PRO, CON = DebateSide.PRO, DebateSide.CON


# Mac dinh tu muc 2.18 la turn_full_v5. File nay kiem tra hanh vi v4 tro xuong -> GHIM v4 cho test qua API (test tu dat
# Settings rieng thi khong bi ghi de vi fixture nay chay TRUOC than test).
V4_SETTINGS = Settings(_env_file=None, turn_generator_version="turn_full_v4")


@pytest.fixture(autouse=True)
def pin_turn_full_v4(request):
    if "client" in request.fixturenames:
        request.getfixturevalue("client")
        app.dependency_overrides[get_settings] = lambda: V4_SETTINGS


def _ctx_burden(ai_side, turn, burden, history=()):
    ctx = _ctx(ai_side, turn, history)
    ctx.ai_burden = burden
    return ctx


# ---------------- prompt v4 ----------------


def test_v4_adds_burden_to_system_and_constraints():
    ctx = _ctx_burden(CON, 4, BC, [_sp(3, CON, "Phản bác learner.")])
    system, user = tf.build_full_prompt(TurnMode.REBUTTAL, ctx, version="turn_full_v4")
    sentence = f"BẠN là phe Phản đối. Mọi điều bạn nói phải chứng minh: {BC}"
    assert system.endswith("Phe của bạn không bao giờ thay đổi.\n" + sentence)
    block = tf.constraints_block(ctx, "turn_full_v4")
    assert block.startswith("Ràng buộc bắt buộc:\n- Bạn thuộc phe Phản đối và phải bảo vệ phe này đến hết trận.\n- "
                            + sentence + "\n")
    assert user.endswith(block) and user.count(sentence) == 1 and system.count(sentence) == 1
    # v4 = v3 + dung 1 cau (system) + dung 1 dong (rang buoc)
    s3, u3 = tf.build_full_prompt(TurnMode.REBUTTAL, ctx, version="turn_full_v3")
    assert system.replace("\n" + sentence, "") == s3 and user.replace("\n- " + sentence, "") == u3


def test_v4_without_burden_is_exactly_v3():
    ctx = _ctx_burden(PRO, 6, None, [_sp(5, PRO, "Tổng kết learner.")])
    for version in ("turn_full_v4", "turn_full_v4_noburden"):
        assert tf.build_full_prompt(TurnMode.CLOSING, ctx, version=version) == \
               tf.build_full_prompt(TurnMode.CLOSING, ctx, version="turn_full_v3")
    with_burden = _ctx_burden(PRO, 6, BP)
    # noburden KHONG dua burden ke ca khi context co (version quyet dinh)
    assert BP not in "".join(tf.build_full_prompt(TurnMode.CLOSING, with_burden, version="turn_full_v4_noburden"))


async def test_v4_generator_version_label_depends_on_burden():
    for burden, label in ((BP, "turn_full_v4"), (None, "turn_full_v4_noburden")):
        gen = tf.FullTurnGeneratorV4(FakeLLMClient([_out(TurnMode.OPENING_FIRST)]), Settings(_env_file=None))
        result = await gen.generate(TurnMode.OPENING_FIRST, _ctx_burden(PRO, 1, burden))
        assert result.text and result.generator_version == label and result.calls[0].prompt_version == label


def test_defaults():
    s = Settings(_env_file=None)
    assert (s.case_plan_prompt_version, s.turn_generator_version, s.turn_burden_enabled) == (
        "case_plan_v7", "turn_full_v7", True)  # mac dinh luot noi v7 tu muc 3.2


# ---------------- qua API ----------------


async def _ready_with_burden(client, fake_llm, fake_reviewer, ai_side="con", burdens=True):
    payload = {"external_session_id": f"main-burden-{ai_side}-{burdens}-{id(fake_llm)}", "motion": P1["text"],
               "ai_side": ai_side, "learner_side": "pro" if ai_side == "con" else "con", "difficulty": "medium"}
    if burdens:
        payload |= {"burden_pro": BP, "burden_con": BC}
    fake_llm.responses = [json.dumps(VALID_CASE_FILE, ensure_ascii=False)]
    fake_reviewer.default_position = "phan_doi_kien_nghi" if ai_side == "con" else "ung_ho_kien_nghi"
    resp = await client.post("/opponent/sessions", json=payload)
    assert resp.status_code == 201, resp.text
    fake_llm.calls.clear()
    return payload["external_session_id"]


async def test_session_with_burden_uses_v7_and_turn_v4(client, db_session, fake_llm, fake_reviewer):
    ext = await _ready_with_burden(client, fake_llm, fake_reviewer)
    sid = await _session_id(db_session, ext)
    case = await db_session.scalar(select(OpponentCaseFile).where(OpponentCaseFile.session_id == sid))
    assert case.prompt_version == "case_plan_v7"  # mac dinh v7 khi co burden

    fake_llm.responses = [_out(TurnMode.OPENING_REPLY)]
    assert (await _turn(client, ext, 2, [_learner(1)])).status_code == 201
    call = fake_llm.calls[0]
    sentence = f"BẠN là phe Phản đối. Mọi điều bạn nói phải chứng minh: {BC}"
    assert sentence in call["system"] and f"- {sentence}" in call["user"]
    turn = await db_session.scalar(select(OpponentTurn).where(OpponentTurn.session_id == sid))
    assert turn.generator_version == "turn_full_v4"
    row = await db_session.scalar(select(OpponentLLMCall).where(
        OpponentLLMCall.turn_id == turn.id, OpponentLLMCall.purpose == LLMCallPurpose.TURN))
    assert row.prompt_version == "turn_full_v4"


async def test_session_without_burden_uses_v5_and_turn_v4_noburden(client, db_session, fake_llm, fake_reviewer):
    ext = await _ready_with_burden(client, fake_llm, fake_reviewer, burdens=False)
    sid = await _session_id(db_session, ext)
    case = await db_session.scalar(select(OpponentCaseFile).where(OpponentCaseFile.session_id == sid))
    assert case.prompt_version == "case_plan_v5"  # khong burden -> giu hanh vi cu
    fake_llm.responses = [_out(TurnMode.OPENING_REPLY)]
    assert (await _turn(client, ext, 2, [_learner(1)])).status_code == 201
    assert "Mọi điều bạn nói phải chứng minh" not in fake_llm.calls[0]["system"] + fake_llm.calls[0]["user"]
    turn = await db_session.scalar(select(OpponentTurn).where(OpponentTurn.session_id == sid))
    assert turn.generator_version == "turn_full_v4_noburden"


async def test_turn_burden_flag_off_for_ablation(client, db_session, fake_llm, fake_reviewer):
    ext = await _ready_with_burden(client, fake_llm, fake_reviewer, ai_side="pro")
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, turn_generator_version="turn_full_v4", turn_burden_enabled=False)
    fake_llm.responses = [_out(TurnMode.OPENING_FIRST)]
    assert (await _turn(client, ext, 1)).status_code == 201
    assert BP not in fake_llm.calls[0]["system"] + fake_llm.calls[0]["user"]
    sid = await _session_id(db_session, ext)
    turn = await db_session.scalar(select(OpponentTurn).where(OpponentTurn.session_id == sid))
    assert turn.generator_version == "turn_full_v4_noburden"
    session = await db_session.get(OpponentSession, sid)
    assert session.burden_pro == BP  # burden van luu; chi luot noi khong dua vao


# ---------------- try_match ----------------


@pytest.mark.parametrize("side", ["pro", "con"])
def test_m01_fixtures_have_p1_burdens(side):
    data = tm.load_fixture("M01", side)
    assert (data["burden_pro"], data["burden_con"]) == (BP, BC)
    assert data["motion"] == P1["text"]


@pytest.mark.parametrize("use_burden,case_version,turn_version", [
    (True, "case_plan_v7", "turn_full_v4"), (False, "case_plan_v5", "turn_full_v4_noburden")])
async def test_try_match_sends_fixture_burdens(db_session, monkeypatch, use_burden, case_version, turn_version):
    from app.opponent import turn_generators

    async def _no_sleep(_s):
        return None

    monkeypatch.setattr(turn_generators, "_sleep", _no_sleep)
    fake = FakeLLMClient([json.dumps(VALID_CASE_FILE, ensure_ascii=False), _out(TurnMode.OPENING_REPLY),
                          _out(TurnMode.REBUTTAL), _out(TurnMode.CLOSING)])
    lines: list[str] = []
    ext = f"try-match-burden-{use_burden}"
    result = await tm.run_match(db_session, V4_SETTINGS, tm.load_fixture("M01", "pro"), PRO,
                                OpponentDifficulty.MEDIUM, ext, lambda: fake, lambda: FakeStanceReviewer(),
                                out=lines.append, use_burden=use_burden)
    assert result["ok"], result["error"]
    sid = await _session_id(db_session, ext)
    session = await db_session.get(OpponentSession, sid)
    assert (session.burden_pro is not None) is use_burden
    case = await db_session.scalar(select(OpponentCaseFile).where(OpponentCaseFile.session_id == sid))
    assert case.prompt_version == case_version
    turns = (await db_session.scalars(select(OpponentTurn).where(OpponentTurn.session_id == sid))).all()
    assert {t.generator_version for t in turns} == {turn_version}
    assert any(("Ganh nang chung minh: CO" if use_burden else "Ganh nang chung minh: KHONG") in x for x in lines)
