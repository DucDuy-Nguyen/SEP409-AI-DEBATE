"""Test audit log raw output + xoay vong theo dung luong. KHONG goi API that."""
import json

import pytest

from app.config import Settings
from app.schemas import ArgumentTurn, DebateSide, DebateStage, RoundEvaluationRequest, TurnSpeaker
from app.services import audit_log
from app.services.llm_client import LLMClient
from app.services.round_evaluator import evaluate_round


class FixedClient(LLMClient):
    def __init__(self, responses: list):
        self.responses = list(responses)

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _payload() -> str:
    criteria = [
        {"name": n, "score": 4, "reasoning": "x"} for n in ("Logic", "Evidence", "Relevance", "Structure", "Persuasiveness")
    ]
    return json.dumps({"criteria": criteria, "consistency_note": "On dinh.", "weaknesses": []})


def _request() -> RoundEvaluationRequest:
    return RoundEvaluationRequest(
        motion="M",
        side=DebateSide.PRO,
        stage=DebateStage.REBUTTAL,
        turns=[ArgumentTurn(speaker=TurnSpeaker.LEARNER, text="IAEA ra đời để giám sát hạt nhân.")],
    )


def _use_settings(monkeypatch, path, **overrides) -> None:
    settings = Settings(eval_audit_log_path=str(path), _env_file=None, **overrides)
    monkeypatch.setattr(audit_log, "get_settings", lambda: settings)


def _record(label: str = "round") -> None:
    audit_log.record_llm_attempt(label, 1, "system", "user", "x" * 200, None)


def test_records_every_attempt_including_failures(tmp_path, monkeypatch):
    path = tmp_path / "nested" / "audit.jsonl"
    _use_settings(monkeypatch, path)

    evaluate_round(_request(), llm_client=FixedClient(["khong phai json", _payload()]))

    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [(r["label"], r["attempt"], r["error"] is None) for r in records] == [("round", 1, False), ("round", 2, True)]
    assert records[0]["raw_output"] == "khong phai json"
    assert records[1]["raw_output"] == _payload()
    assert "IAEA" in records[1]["user_prompt"]


def test_records_provider_errors_that_are_not_retried(tmp_path, monkeypatch):
    path = tmp_path / "audit.jsonl"
    _use_settings(monkeypatch, path)

    with pytest.raises(RuntimeError):
        evaluate_round(_request(), llm_client=FixedClient([RuntimeError("provider down")]))

    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["raw_output"] is None
    assert "provider down" in record["error"]


def test_write_failure_does_not_break_grading(tmp_path, monkeypatch):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    _use_settings(monkeypatch, blocker / "audit.jsonl")

    result = evaluate_round(_request(), llm_client=FixedClient([_payload()]))

    assert result.round_score == 8.0


def test_can_be_disabled(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _use_settings(monkeypatch, "")

    evaluate_round(_request(), llm_client=FixedClient([_payload()]))

    assert list(tmp_path.iterdir()) == []


def test_rotates_when_over_the_limit_and_keeps_only_the_configured_backups(tmp_path, monkeypatch):
    path = tmp_path / "audit.jsonl"
    _use_settings(monkeypatch, path, eval_audit_log_max_bytes=600, eval_audit_log_backups=2)

    for i in range(12):
        _record(f"call-{i}")

    files = sorted(p.name for p in tmp_path.iterdir())
    assert files == ["audit.jsonl", "audit.jsonl.1", "audit.jsonl.2"]
    assert all(p.stat().st_size <= 600 for p in tmp_path.iterdir())
    # File moi nhat giu ban ghi moi nhat, .1 cu hon, va khong ban ghi nao bi tach doi giua cac file.
    newest = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    backup = [json.loads(line) for line in (tmp_path / "audit.jsonl.1").read_text(encoding="utf-8").splitlines()]
    assert newest[-1]["label"] == "call-11"
    assert int(backup[-1]["label"].split("-")[1]) + 1 == int(newest[0]["label"].split("-")[1])


def test_zero_backups_deletes_the_old_file_instead_of_growing(tmp_path, monkeypatch):
    path = tmp_path / "audit.jsonl"
    _use_settings(monkeypatch, path, eval_audit_log_max_bytes=600, eval_audit_log_backups=0)

    for i in range(12):
        _record(f"call-{i}")

    assert [p.name for p in tmp_path.iterdir()] == ["audit.jsonl"]
    assert path.stat().st_size <= 600


def test_zero_max_bytes_means_no_rotation(tmp_path, monkeypatch):
    path = tmp_path / "audit.jsonl"
    _use_settings(monkeypatch, path, eval_audit_log_max_bytes=0)

    for i in range(5):
        _record(f"call-{i}")

    assert [p.name for p in tmp_path.iterdir()] == ["audit.jsonl"]
    assert len(path.read_text(encoding="utf-8").splitlines()) == 5
