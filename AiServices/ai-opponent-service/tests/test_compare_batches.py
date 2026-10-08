"""
scripts/compare_case_plan_batches.py: gop nhieu file / phien ban, chi so cau hinh chung (bao thieu),
tach nhom vague_evidence (ai_fields / learner_claim / unknown), doc dang cu.
Batch runner voi --prompt-version (chon qua Settings).
"""
import json

from app.core.config import Settings
from scripts.compare_case_plan_batches import compare, load_group, metrics, pair_groups, vague_stats
from scripts.eval_common import load_jsonl
from scripts.run_case_plan_batch import build_runs, run_batch
from tests.conftest import VALID_CASE_FILE, FakeLLMClient


def _attempt(
    purpose="case_plan", *, success=True, failure_kind=None, verdict=None, schema_rejected=False,
    retry_feedback=None, wait_ms=None,
):
    return {
        "attempt": 1, "purpose": purpose, "latency_ms": 10, "success": success, "error": None,
        "schema_rejected": schema_rejected, "failure_kind": failure_kind, "retry_feedback": retry_feedback,
        "reviewer_verdict": verdict, "reviewer_detail": None, "vague_evidence": None, "raw_output": None,
        "tokens_in": None, "tokens_out": None, "rate_limit_wait_ms": wait_ms,
    }


def _run(motion, side, difficulty, *, status="ready", attempts=None, vague=None, latency=1000,
         version="case_plan_v3", run_index=0, rerun_of=None):
    return {
        "run_index": run_index, "motion": motion, "ai_side": side, "difficulty": difficulty, "prompt_version": version,
        "final_status": status, "total_latency_ms": latency, "final_vague_evidence": vague, "rerun_of": rerun_of,
        "case_file": {"x": 1} if status == "ready" else None,
        "attempts": attempts if attempts is not None else [_attempt(), _attempt("stance_review")],
    }


def _write(path, records):
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records), encoding="utf-8")
    return path


def test_multiple_files_per_version_are_merged(tmp_path):
    a1 = _write(tmp_path / "v3_a.jsonl", [_run("M1", "pro", "easy"), _run("M1", "con", "medium", run_index=1)])
    a2 = _write(tmp_path / "v3_b.jsonl", [_run("M1", "pro", "easy", status="invalid_output")])  # chay lap

    records, replaced = load_group([a1, a2])

    assert len(records) == 3 and replaced == 0
    assert {r["_source"] for r in records} == {"v3_a.jsonl", "v3_b.jsonl"}


def test_rerun_file_replaces_llm_error_of_original(tmp_path):
    original = _write(
        tmp_path / "orig.jsonl",
        [_run("M1", "pro", "easy", run_index=0), _run("M1", "con", "medium", status="llm_error", run_index=1)],
    )
    rerun = _write(tmp_path / "orig_rerun.jsonl", [_run("M1", "con", "medium", run_index=1, rerun_of="orig.jsonl")])

    records, replaced = load_group([original, rerun])

    assert replaced == 1
    assert [(r["run_index"], r["final_status"]) for r in records] == [(0, "ready"), (1, "ready")]


def test_pairs_only_common_configs_and_reports_missing():
    groups = {
        "v3": [_run("M1", "pro", "easy"), _run("M1", "con", "medium"), _run("M2", "pro", "hard"), _run("M1", "pro", "easy")],
        "v4": [_run("M1", "pro", "easy"), _run("M1", "con", "hard"), _run("M3", "pro", "easy")],
    }

    paired = pair_groups(groups)

    assert paired["common"] == {("M1", "pro", "easy")}
    assert paired["missing"]["v3"] == [("M1", "con", "medium"), ("M2", "pro", "hard")]
    assert paired["missing"]["v4"] == [("M1", "con", "hard"), ("M3", "pro", "easy")]
    assert len(paired["paired"]["v3"]) == 2  # 2 lan chay lap cua cau hinh chung deu duoc giu


def test_vague_evidence_split_by_field_group_including_old_format():
    runs = [
        _run("M1", "pro", "easy", vague=[
            {"phrase": "%", "field": "arguments[0].reasoning"},
            {"phrase": "nghiên cứu", "field": "arguments[1].title"},
            {"phrase": "nhiều quốc gia", "field": "anticipated_opponent_arguments[2].learner_claim"},
        ]),
        _run("M2", "con", "medium", vague=[{"phrase": "%", "field": "weighing"}]),
        _run("M3", "pro", "hard", vague=["chứng minh", "%"]),  # dang cu: list chuoi, khong co truong
        _run("M4", "con", "easy", status="llm_error", vague=[{"phrase": "%", "field": "weighing"}]),  # khong co case file
    ]

    stats = vague_stats(runs)

    assert stats["ai_fields"]["case_files_with_hits"] == 2 and stats["ai_fields"]["hits"] == 3
    assert dict(stats["ai_fields"]["by_phrase"]) == {"%": 2, "nghiên cứu": 1}
    assert stats["learner_claim"]["case_files_with_hits"] == 1 and stats["learner_claim"]["hits"] == 1
    assert dict(stats["learner_claim"]["by_phrase"]) == {"nhiều quốc gia": 1}
    assert stats["unknown"]["case_files_with_hits"] == 1 and stats["unknown"]["hits"] == 2


def test_metrics():
    runs = [
        _run("M1", "pro", "easy", attempts=[
            _attempt(success=False, failure_kind="side_flip", verdict="side_flip", retry_feedback="fb"),
            _attempt("stance_review"), _attempt(verdict="pass"), _attempt("stance_review"),
        ]),
        _run("M2", "con", "medium", status="invalid_output", attempts=[
            _attempt(success=False, failure_kind="rate_limited", wait_ms=9000),
            _attempt(success=False, failure_kind="schema_rejected", schema_rejected=True, retry_feedback="fb"),
            _attempt(success=False, failure_kind="banned_phrase"),
        ], latency=3000),
        _run("M3", "pro", "hard", vague=[{"phrase": "thống kê", "field": "weighing"}], latency=2000),
    ]

    m = metrics(runs)
    m.pop("vague")

    assert m == {
        "n": 3, "success": 2, "runs_with_side_flip": 1, "side_flip_attempts": 1, "schema_rejected": 1,
        "banned_phrase_rejected": 1, "avg_content_retries": round(2 / 3, 2), "rate_limit_waits": 1,
        "avg_latency_ms": 2000,
    }


def test_compare_prints_tables_for_common_configs(tmp_path):
    v3 = [
        _write(tmp_path / "a_v3.jsonl", [_run("M1", "pro", "easy", vague=[{"phrase": "%", "field": "weighing"}]),
                                         _run("M2", "con", "medium", status="invalid_output")]),
        _write(tmp_path / "b_v3.jsonl", [_run("M1", "pro", "easy")]),
    ]
    v4 = [_write(tmp_path / "c_v4.jsonl", [
        _run("M1", "pro", "easy", version="case_plan_v4", latency=500),
        _run("M2", "con", "medium", version="case_plan_v4"),
        _run("M9", "pro", "hard", version="case_plan_v4"),
    ])]

    out = compare({"v3": v3, "v4": v4})

    assert "v3: 2 file, 3 lan chay, prompt_version=case_plan_v3" in out
    assert "Cau hinh (motion, ai_side, difficulty) chung: 2" in out
    assert "Chi co o v4 (bi bo qua, 1):" in out and "- M9 | pro | hard" in out
    assert "So lan chay tren cau hinh chung: v3=3, v4=2" in out
    success_row = next(line for line in out.splitlines() if line.startswith("| Thanh cong"))
    assert "2/3 (67%)" in success_row and "2/2 (100%)" in success_row
    ai_row = next(line for line in out.splitlines() if "ai_fields: case file co hit" in line)
    assert "1/2 (50%)" in ai_row and "0/2 (0%)" in ai_row
    assert '"%"' in out
    assert "unknown" not in out  # khong co du lieu cu -> khong in nhom unknown


def test_compare_warns_when_version_label_does_not_match(tmp_path):
    v3 = [_write(tmp_path / "a.jsonl", [_run("M1", "pro", "easy")])]
    v4 = [_write(tmp_path / "b.jsonl", [_run("M1", "pro", "easy")])]  # that ra la v3
    assert "CANH BAO: nhom v4 chua file prompt_version khac" in compare({"v3": v3, "v4": v4})


def test_load_jsonl_tags_source(tmp_path):
    path = _write(tmp_path / "x.jsonl", [_run("M1", "pro", "easy")])
    [record] = load_jsonl(path)
    assert record["_source"] == "x.jsonl" and record["_source_path"] == str(path)


async def test_batch_prompt_version_v3(tmp_path):
    runs = build_runs([{"id": "M01", "motion": "Nên cấm dạy thêm"}])[:1]
    planner = FakeLLMClient([json.dumps({**VALID_CASE_FILE, "arguments": VALID_CASE_FILE["arguments"][:2]})])
    settings = Settings(_env_file=None).model_copy(update={"case_plan_prompt_version": "case_plan_v3"})

    [record] = await run_batch(runs, planner, None, settings, tmp_path / "x.jsonl", log=lambda _: None)

    assert record["prompt_version"] == "case_plan_v3" and record["final_status"] == "ready"
