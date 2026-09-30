"""scripts/try_match.run_match voi DB test + LLM gia: dung gon khi 1 luot AI that bai, tong thoi gian cho 429."""
import json

import pytest

from app.core.config import Settings
from app.opponent.match_format import TurnMode
from app.opponent.models import DebateSide, OpponentDifficulty
from scripts import try_match as tm
from tests.conftest import VALID_CASE_FILE, FakeLLMClient, FakeStanceReviewer, RateLimited
from tests.test_turn_full import _out


@pytest.fixture(autouse=True)
def no_real_sleep(monkeypatch):
    """Cho 429 van duoc GHI (rate_limit_wait_ms) nhung khong ngu that."""
    from app.opponent import turn_generators

    async def _no_sleep(_seconds):
        return None

    monkeypatch.setattr(turn_generators, "_sleep", _no_sleep)


async def _run(db_session, responses, external_id="try-match-test"):
    fake = FakeLLMClient([json.dumps(VALID_CASE_FILE, ensure_ascii=False), *responses])
    reviewer = FakeStanceReviewer("phan_doi_kien_nghi")  # learner pro -> AI con
    lines: list[str] = []
    result = await tm.run_match(
        db_session, Settings(_env_file=None), tm.load_fixture("M01", "pro"), DebateSide.PRO,
        OpponentDifficulty.MEDIUM, external_id, lambda: fake, lambda: reviewer, out=lines.append,
    )
    return result, "\n".join(lines), fake


async def test_failed_turn_stops_cleanly_with_calls_and_total_429_wait(db_session):
    responses = [
        RateLimited("Please try again in 1.5s."), _out(TurnMode.OPENING_REPLY),  # luot 2: cho 429 roi thanh cong
        RateLimited("Please try again in 2s."), "khong phai json", "van sai", "sai lan 3",  # luot 4: that bai
    ]
    result, printed, fake = await _run(db_session, responses)

    assert result["ok"] is False and result["failed_turn"] == 4 and "TurnGenerationError" in result["error"]
    assert "=> LUOT 4 THAT BAI: TurnGenerationError" in printed
    assert "[cac lan goi cua luot 4] 4" in printed and "  - lan 1 (sinh): rate_limited (cho 2000 ms)" in printed
    assert "  - lan 2 (sinh): invalid_json" in printed
    assert "Traceback" not in printed
    assert result["rate_limit_wait_ms"] == 3500 and result["rate_limit_waits"] == 2  # ca tran (jitter tat trong test)
    assert "Tong cho 429 ca tran: 3.5s (2 lan)" in printed
    speakers = [(x["turn_index"], x["speaker"], x.get("failed", False)) for x in result["transcript"]]
    assert speakers == [(1, "learner", False), (2, "ai", False), (3, "learner", False), (4, "ai", True)]
    assert [c["failure_kind"] for c in result["transcript"][-1]["calls"]] == [
        "rate_limited", "invalid_json", "invalid_json", "invalid_json"]


async def test_full_match_prints_analysis_and_wait_total(db_session):
    responses = [_out(TurnMode.OPENING_REPLY), _out(TurnMode.REBUTTAL), _out(TurnMode.CLOSING)]
    result, printed, _ = await _run(db_session, responses, "try-match-test-ok")
    assert result["ok"] and result["failed_turn"] is None
    assert [x["turn_index"] for x in result["transcript"] if x["speaker"] == "ai"] == [2, 4, 5]
    assert "[target_premise] Học sinh tự kiểm soát được." in printed and "[ai_points]" in printed
    assert "[lan thu lai] 0" in printed and "Tong cho 429 ca tran: 0.0s (0 lan)" in printed


async def test_case_planning_failure_also_stops_cleanly(db_session):
    fake = FakeLLMClient([RuntimeError("503 groq down")])
    lines: list[str] = []
    result = await tm.run_match(
        db_session, Settings(_env_file=None), tm.load_fixture("M01", "pro"), DebateSide.PRO,
        OpponentDifficulty.MEDIUM, "try-match-test-cp", lambda: fake, lambda: None, out=lines.append,
    )
    assert result["ok"] is False and result["failed_turn"] is None and "LLMCallError" in result["error"]
    assert any("Case Planning THAT BAI" in x for x in lines)


async def test_per_turn_429_wait_printed(db_session):
    from tests.conftest import RateLimited as _RL

    responses = [_RL("Please try again in 2s."), _RL("Please try again in 1s."), _out(TurnMode.OPENING_REPLY),
                 _out(TurnMode.REBUTTAL), _out(TurnMode.CLOSING)]
    result, printed, _ = await _run(db_session, responses, "try-match-test-wait")
    assert result["ok"] and "cho 429 3.0s" in printed
    assert result["transcript"][1]["rate_limit_wait_ms"] == 3000
