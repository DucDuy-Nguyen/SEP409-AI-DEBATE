"""
Learner BO LUOT (het gio khong noi / bam bo luot): FE gui skipped=true (hoac chuoi giu cho cu). AI van noi luot cua minh,
noi ro doi phuong khong phat bieu, bao ve case; khong chon target_premise, khong gan loi chua noi cho learner.
"""
import json

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.opponent import turn_full as tf
from app.opponent.match_format import TurnMode
from app.opponent.models import OpponentSpeech
from app.opponent.schemas import SKIPPED_SPEECH_TEXT, LearnerSpeechIn, is_skipped_speech
from tests.test_turn_full import CON, _ctx, _out, _sp
from tests.test_turns_api import _learner, _ready_session, _session_id, _turn

MOTION_SIDE_CON = "con"


# ---------------- schema ----------------


def test_skipped_flag_and_legacy_placeholders_become_one_stored_text():
    a = LearnerSpeechIn(turn_index=3, round_type="rebuttal", skipped=True)
    assert (a.skipped, a.text) == (True, SKIPPED_SPEECH_TEXT)
    for legacy in ("(Thí sinh không đưa ra phát biểu - Hết thời gian)", "  (Thí sinh chủ động bỏ lượt) "):
        b = LearnerSpeechIn(turn_index=3, round_type="rebuttal", text=legacy)
        assert (b.skipped, b.text) == (True, SKIPPED_SPEECH_TEXT)
    assert is_skipped_speech(SKIPPED_SPEECH_TEXT) and not is_skipped_speech("Mình phản đối.")
    with pytest.raises(ValidationError):
        LearnerSpeechIn(turn_index=3, round_type="rebuttal", text="   ")


# ---------------- prompt / schema of the turn ----------------


def test_rebuttal_after_a_skipped_learner_turn_says_so_and_attacks_no_premise():
    history = [
        _sp(1, CON, "Luật quốc tế giúp chống tin giả."),
        _sp(2, CON, "Mở màn của AI."),
        _sp(3, CON, SKIPPED_SPEECH_TEXT),
    ]
    ctx = _ctx(CON, 4, history)
    assert tf.new_learner_speeches(ctx) == [] and len(tf.skipped_learner_turns(ctx)) == 1

    _, user = tf.build_full_prompt(TurnMode.REBUTTAL, ctx, None, tf.FULL_V3)
    assert "đã bỏ lượt phản bác (không phát biểu)" in user
    assert "KHÔNG gán cho đội" in user
    assert "vừa phát biểu" not in user and SKIPPED_SPEECH_TEXT not in user
    assert "Chọn target_premise" not in user
    assert "- target_premise: null" in user
    assert tf.build_response_schema(TurnMode.REBUTTAL, False)["properties"]["target_premise"] == {"type": "null"}


def test_a_spoken_rebuttal_still_attacks_a_premise():
    history = [_sp(1, CON, "Mở màn learner."), _sp(2, CON, "Mở màn AI."), _sp(3, CON, "Phản biện learner.")]
    _, user = tf.build_full_prompt(TurnMode.REBUTTAL, _ctx(CON, 4, history), None, tf.FULL_V3)
    assert "Chọn target_premise" in user and "bỏ lượt" not in user


# ---------------- API ----------------


def _skip_output(mode: TurnMode) -> str:
    """Model answer when the learner skipped: no claims, no premises, no target."""
    data = json.loads(_out(mode))
    data.update(learner_claims=[], premises={"explicit": [], "implicit": []}, target_premise=None)
    return json.dumps(data, ensure_ascii=False)


async def test_ai_answers_a_skipped_rebuttal_and_the_skip_is_stored(client, db_session, fake_llm, fake_reviewer):
    ext = await _ready_session(client, fake_llm, fake_reviewer, MOTION_SIDE_CON)
    fake_llm.responses = [_out(TurnMode.OPENING_REPLY), _skip_output(TurnMode.REBUTTAL)]
    assert (await _turn(client, ext, 2, [_learner(1, "Luật quốc tế giúp chống tin giả.")])).status_code == 201

    resp = await _turn(client, ext, 4, [{"turn_index": 3, "round_type": "rebuttal", "skipped": True}])

    assert resp.status_code == 201, resp.text  # before: 502, target_premise was required in a rebuttal
    prompt = [c for c in fake_llm.calls if "user" in c and not c.get("chat")][-1]["user"]
    assert "đã bỏ lượt phản bác" in prompt
    sid = await _session_id(db_session, ext)
    stored = await db_session.scalar(
        select(OpponentSpeech.text).where(OpponentSpeech.session_id == sid, OpponentSpeech.turn_index == 3)
    )
    assert stored == SKIPPED_SPEECH_TEXT

    # Same request again (FE retry), even with the old placeholder text: idempotent, no LLM call
    again = await _turn(client, ext, 4, [{"turn_index": 3, "round_type": "rebuttal",
                                          "text": "(Thí sinh không đưa ra phát biểu - Hết thời gian)"}])
    assert again.status_code == 200
