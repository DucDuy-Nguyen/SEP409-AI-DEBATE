"""
So khop bai noi learner voi snapshot da luu: chuan hoa truoc khi so (trim, \\r\\n -> \\n, NFC), va loi "da sinh voi bai noi
khac" tra 409 kem ma loi de client phan biet voi cac 409 tam thoi.
"""
import unicodedata

import pytest

from tests.test_turns_api import _chat_calls, _learner, _ready_session, _turn, baseline_generator  # noqa: F401

SPEECH = "Điện thoại làm học sinh mất tập trung.\nKết quả học tập giảm rõ rệt."
MISMATCH_CODE = "LEARNER_SPEECH_MISMATCH"


@pytest.mark.parametrize(
    "equivalent",
    [
        f"  {SPEECH}\n",
        SPEECH.replace("\n", "\r\n"),
        unicodedata.normalize("NFD", SPEECH),
    ],
    ids=["padded", "crlf", "nfd"],
)
async def test_retry_with_equivalent_text_replays_without_llm(client, fake_llm, fake_reviewer, equivalent):
    ext = await _ready_session(client, fake_llm, fake_reviewer, "con")
    fake_llm.responses = ["AI mở màn."]
    first = await _turn(client, ext, 2, [_learner(1, SPEECH)])
    assert first.status_code == 201

    again = await _turn(client, ext, 2, [_learner(1, equivalent)])

    assert again.status_code == 200, again.text
    assert again.json() == first.json()
    assert len(_chat_calls(fake_llm)) == 1


async def test_equivalent_text_for_a_new_turn_is_not_a_conflict(client, fake_llm, fake_reviewer):
    ext = await _ready_session(client, fake_llm, fake_reviewer, "pro")
    fake_llm.responses = ["AI mở màn.", "AI phản bác."]
    await _turn(client, ext, 1)
    await _turn(client, ext, 3, [_learner(2, SPEECH)])

    resp = await _turn(client, ext, 6, [_learner(2, SPEECH.replace("\n", "\r\n")), _learner(4), _learner(5)])

    assert resp.status_code != 409, resp.text


async def test_another_speech_for_a_generated_turn_is_409_with_code(client, fake_llm, fake_reviewer):
    """Tai hien loi that: luot 2 da sinh tu mot bai noi khac (external_session_id trung voi lan luyen truoc)."""
    ext = await _ready_session(client, fake_llm, fake_reviewer, "con")
    fake_llm.responses = ["AI mở màn."]
    await _turn(client, ext, 2, [_learner(1, SPEECH)])

    resp = await _turn(client, ext, 2, [_learner(1, "Lần luyện thứ hai, một bài nói khác hẳn.")])

    assert resp.status_code == 409
    assert resp.json()["code"] == MISMATCH_CODE
    assert "[1]" in resp.json()["detail"]
    assert len(_chat_calls(fake_llm)) == 1


async def test_another_speech_for_a_stored_turn_is_409_with_code(client, fake_llm, fake_reviewer):
    ext = await _ready_session(client, fake_llm, fake_reviewer, "pro")
    fake_llm.responses = ["AI mở màn.", "AI phản bác."]
    await _turn(client, ext, 1)
    await _turn(client, ext, 3, [_learner(2, SPEECH)])

    resp = await _turn(client, ext, 6, [_learner(2, "Sửa lại bài lượt 2."), _learner(4), _learner(5)])

    assert resp.status_code == 409
    assert resp.json()["code"] == MISMATCH_CODE


async def test_other_conflicts_carry_no_mismatch_code(client, fake_llm, fake_reviewer):
    ext = await _ready_session(client, fake_llm, fake_reviewer, "con")

    resp = await _turn(client, ext, 4, [])  # thieu cac luot truoc

    assert resp.status_code == 409
    assert "code" not in resp.json()
