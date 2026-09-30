"""
Batch runner (scripts/run_case_plan_batch.py) voi LLM gia lap: format JSONL, bang tong hop, 2 chi so tach rieng
(content_retries / rate_limit_waits), token, --only-failed.
"""
import json
import re

import pytest

from app.core.config import Settings
from app.opponent import service
from scripts.run_case_plan_batch import (
    DEFAULT_MOTIONS,
    DEFAULT_PAUSE_SECONDS,
    build_runs,
    format_summary,
    load_motions,
    load_records,
    run_batch,
    runs_from_failed,
    summarize,
)
from tests.conftest import FakeLLMClient, FakeStanceReviewer, RateLimited, SchemaRejected, make_case_file

MOTIONS = [{"id": "M01", "motion": "Nên cấm dạy thêm, học thêm"}, {"id": "M02", "motion": "Nên áp dụng tuần làm việc 4 ngày"}]

RECORD_KEYS = {
    "run_index", "motion_id", "motion", "ai_side", "learner_side", "difficulty", "prompt_version", "provider",
    "model", "reviewer_model", "temperature", "case_plan_max_tokens", "json_schema", "rerun_of", "final_status",
    "total_latency_ms", "final_reviewer_verdict", "final_vague_evidence", "attempts", "case_file",
    "content_retries", "rate_limit_waits", "rate_limit_wait_seconds",
}
ATTEMPT_KEYS = {
    "attempt", "purpose", "latency_ms", "success", "error", "schema_rejected", "failure_kind", "retry_feedback",
    "reviewer_verdict", "reviewer_detail", "vague_evidence", "tokens_in", "tokens_out", "rate_limit_wait_ms",
    "key_repairs", "raw_output",
}


class Groq429(RateLimited):
    """429 kem cau 'try again in Xs' nhu Groq that."""

    def __init__(self, seconds: float):
        super().__init__(f"Rate limit reached ... Please try again in {seconds}s. Need more tokens?")


@pytest.fixture
def slept(monkeypatch) -> list[float]:
    """Ghi lai thoi gian cho 429 thay vi ngu that."""
    waits: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)

    monkeypatch.setattr(service, "_sleep", fake_sleep)
    return waits


def test_motions_v1_has_10_motions_and_20_runs():
    motions = load_motions(DEFAULT_MOTIONS)
    assert len(motions) == 10 and len({m["id"] for m in motions}) == 10
    assert motions[0]["motion"] == "Nên cấm học sinh sử dụng điện thoại trong trường học"
    assert motions[9]["motion"] == "Nên đánh thuế cao đối với đồ uống có đường"
    runs = build_runs(motions)
    assert len(runs) == 20
    assert [r["ai_side"].value for r in runs[:4]] == ["pro", "con", "pro", "con"]
    assert [r["difficulty"].value for r in runs[:6]] == ["easy", "medium", "hard", "easy", "medium", "hard"]
    assert all(r["learner_side"] != r["ai_side"] for r in runs)


def test_default_pause_matches_free_tier_tpm():
    assert DEFAULT_PAUSE_SECONDS == 35


async def test_batch_writes_jsonl_and_summary(tmp_path, slept):
    runs = build_runs(MOTIONS)  # (M01 pro easy), (M01 con medium), (M02 pro hard), (M02 con easy)
    vague = make_case_file(3)
    vague["weighing"] = "Theo thống kê, tình hình đã khác."  # LOW (chi log), khong bi reject
    planner = FakeLLMClient(
        [
            json.dumps(make_case_file(2)), json.dumps(make_case_file(2)),  # run 0: lan 1 bi side_flip -> 1 retry
            Groq429(7.5), SchemaRejected(), json.dumps(make_case_file(3)),  # run 1: 429 (cho) + schema -> 1 retry
            json.dumps(vague),  # run 2: vague_evidence
            Groq429(2.0), Groq429(3.0), json.dumps(make_case_file(2)),  # run 3: 2 lan cho 429, 0 retry
        ]
    )
    planner.usages = [
        {"tokens_in": 1000, "tokens_out": 2000}, {"tokens_in": 1100, "tokens_out": 2200},  # run 0
        {"tokens_in": 1000, "tokens_out": 3000},  # run 1 (lan thanh cong)
        {"tokens_in": 1200, "tokens_out": 3500},  # run 2
        {"tokens_in": 900, "tokens_out": 1500},  # run 3
    ]
    reviewer = FakeStanceReviewer(default_position="khong_ro")
    reviewer.responses = [  # lan review dau (run 0, ai_side=pro): moi muc phan doi -> lat phe (dinh dang v1)
        json.dumps(
            {
                "arguments": [{"id": i, "position": "phan_doi_kien_nghi", "reason": "r"} for i in ("A1", "A2")],
                "weighing": {"position": "phan_doi_kien_nghi", "reason": "r"},
            }
        )
    ]
    out = tmp_path / "case_plan" / "batch.jsonl"
    logs: list[str] = []

    records = await run_batch(runs, planner, reviewer, Settings(_env_file=None), out, log=logs.append)

    lines = load_records(out)
    assert lines == records and len(lines) == 4
    for line in lines:
        assert set(line) == RECORD_KEYS
        assert all(set(a) == ATTEMPT_KEYS for a in line["attempts"])
        assert line["prompt_version"] == "case_plan_v5" and line["model"] == "fake-model"
        assert line["reviewer_model"] == "fake-reviewer" and line["rerun_of"] is None
    assert [(r["motion_id"], r["ai_side"], r["difficulty"]) for r in lines] == [
        ("M01", "pro", "easy"), ("M01", "con", "medium"), ("M02", "pro", "hard"), ("M02", "con", "easy"),
    ]
    # 2 chi so tach rieng theo tung lan chay
    assert [(r["content_retries"], r["rate_limit_waits"], r["rate_limit_wait_seconds"]) for r in lines] == [
        (1, 0, 0), (1, 1, 7.5), (0, 0, 0), (0, 2, 5.0),
    ]
    assert slept == [7.5, 2.0, 3.0]  # cho DUNG thoi gian Groq yeu cau (jitter tat trong test)
    run0 = lines[0]
    assert [a["purpose"] for a in run0["attempts"]] == ["case_plan", "stance_review"] * 2
    assert run0["attempts"][0]["reviewer_verdict"] == "side_flip"
    assert (run0["attempts"][0]["tokens_in"], run0["attempts"][0]["tokens_out"]) == (1000, 2000)
    assert lines[1]["attempts"][0]["failure_kind"] == "rate_limited" and lines[1]["attempts"][0]["rate_limit_wait_ms"] == 7500
    assert lines[1]["attempts"][1]["schema_rejected"] is True
    assert lines[2]["final_vague_evidence"] == [
        {"phrase": "thống kê / theo báo cáo", "field": "weighing", "level": "low", "rule": "thong_ke", "match": "thống kê"}
    ]
    assert all(r["final_status"] == "ready" for r in lines)
    # log in token tung lan goi
    assert any("#1  case_plan     in= 1000 out= 2000" in line for line in logs)
    assert any("rate_limited -> cho 7.5s" in line for line in logs)

    summary = summarize(records)
    assert summary == {
        "runs": 4,
        "success": 4,
        "final_status": {"ready": 4},
        "side_flip_caught": 1,
        "runs_with_side_flip": 1,
        "final_unclear": 4,  # reviewer gia lap tra "khong_ro" cho moi lan con lai
        "schema_rejected": 1,
        "case_files_with_vague_evidence": 1,
        "banned_phrase_rejected": 0,
        "key_repaired": 0,
        "content_retries": 2,
        "avg_content_retries": 0.5,
        "rate_limit_waits": 3,
        "rate_limit_wait_seconds": 12.5,
        "case_plan_calls": 9,  # ke ca 3 lan bi 429 va 1 lan bi Groq tu choi schema
        "case_plan_tokens_out_avg": 2440,  # (2000+2200+3000+3500+1500)/5
        "case_plan_tokens_out_max": 3500,
        "case_plan_max_tokens": 4000,
        "avg_latency_ms": summary["avg_latency_ms"],
    }
    table = format_summary(summary)
    assert re.search(r"\| content_retries \(tong / tb lan chay\)\s*\| 2 / 0\.5 ", table)
    assert re.search(r"\| rate_limit_waits \(lan / tong giay\)\s*\| 3 / 12\.5s ", table)
    assert "2440 / 3500 (max_tokens=4000)" in table


async def test_rate_limit_waits_do_not_consume_case_plan_attempts(tmp_path, slept):
    # max_attempts=1: 3 lan 429 roi thanh cong van la ready; content_retries = 0
    runs = build_runs(MOTIONS[:1])[1:2]  # (M01, con, medium)
    planner = FakeLLMClient([Groq429(1.0), Groq429(1.0), Groq429(1.0), json.dumps(make_case_file(3))])
    settings = Settings(_env_file=None, case_plan_max_attempts=1)

    [record] = await run_batch(runs, planner, None, settings, tmp_path / "x.jsonl", log=lambda _: None)

    assert record["final_status"] == "ready"
    assert record["content_retries"] == 0 and record["rate_limit_waits"] == 3


async def test_batch_records_failed_run(tmp_path):
    runs = build_runs(MOTIONS[:1])[:1]
    planner = FakeLLMClient([RuntimeError("401 invalid api key")])
    out = tmp_path / "b.jsonl"

    [record] = await run_batch(runs, planner, None, Settings(_env_file=None), out, log=lambda _: None)

    assert record["final_status"] == "llm_error" and record["case_file"] is None
    assert record["reviewer_model"] is None
    assert load_records(out) == [record]


async def test_only_failed_reruns_llm_error_configs(tmp_path):
    runs = build_runs(MOTIONS)
    old = tmp_path / "old.jsonl"
    statuses = ["ready", "llm_error", "invalid_output", "llm_error"]
    old.write_text(
        "\n".join(
            json.dumps(
                {"run_index": r["run_index"], "motion_id": r["motion_id"], "motion": r["motion"],
                 "ai_side": r["ai_side"].value, "learner_side": r["learner_side"].value,
                 "difficulty": r["difficulty"].value, "prompt_version": "case_plan_v3", "final_status": st}
            )
            for r, st in zip(runs, statuses)
        ),
        encoding="utf-8",
    )

    rerun = runs_from_failed(load_records(old))

    assert [(r["run_index"], r["motion_id"], r["ai_side"].value, r["difficulty"].value) for r in rerun] == [
        (1, "M01", "con", "medium"), (3, "M02", "con", "easy"),
    ]
    planner = FakeLLMClient([json.dumps(make_case_file(3)), json.dumps(make_case_file(2))])
    records = await run_batch(
        rerun, planner, None, Settings(_env_file=None), tmp_path / "rerun.jsonl", log=lambda _: None, rerun_of="old.jsonl"
    )
    assert [r["final_status"] for r in records] == ["ready", "ready"]
    assert all(r["rerun_of"] == "old.jsonl" for r in records)
    assert [r["run_index"] for r in records] == [1, 3]  # giu run_index goc de doi chieu
