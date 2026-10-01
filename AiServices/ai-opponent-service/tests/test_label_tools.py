"""
scripts/label_stance.py (gan nhan phe MU) va scripts/label_vague_evidence.py (gan nhan hit) — du lieu JSONL gia lap,
input gia lap. Khong goi LLM.
"""
import json
import re

import pytest

from scripts import label_stance as ls
from scripts import label_vague_evidence as lv
from scripts.eval_common import load_jsonl, read_csv

REVIEWER_MARK = "LYDO_REVIEWER_BI_MAT"


def _case(claims: dict[str, str], weighing: str) -> str:
    return json.dumps(
        {
            "motion_interpretation": "Cách hiểu kiến nghị.",
            "definitions": [],
            "arguments": [
                {"id": i, "title": f"T{i}", "claim": c, "reasoning": f"Lý do cho {i}. " * 30, "example": "Giả sử...",
                 "impact": "Tác động."}
                for i, c in claims.items()
            ],
            "anticipated_opponent_arguments": [],
            "weighing": weighing,
        },
        ensure_ascii=False,
    )


def _plan_attempt(n, claims, weighing, positions, verdict, *, vague=None):
    return {
        "attempt": n, "purpose": "case_plan", "success": verdict != "side_flip", "raw_output": _case(claims, weighing),
        "reviewer_verdict": verdict, "vague_evidence": vague,
        "reviewer_detail": {
            "positions": [{"id": i, "position": p, "reason": f"{REVIEWER_MARK} {i}"} for i, p in positions.items()],
        },
    }


def _record(run_index, motion_id, ai_side, difficulty, attempts, motion="Nên cấm xe máy ở nội thành"):
    return {"run_index": run_index, "motion_id": motion_id, "motion": motion, "ai_side": ai_side,
            "difficulty": difficulty, "final_status": "ready", "attempts": attempts}


UH, PD, KR = "ung_ho_kien_nghi", "phan_doi_kien_nghi", "khong_ro"


@pytest.fixture
def batch_file(tmp_path):
    records = [
        # lan chay 0 (pro): lan thu 1 bi reviewer bao side_flip (A2), lan thu 2 pass
        _record(0, "M07", "pro", "easy", [
            _plan_attempt(1, {"A1": "Giảm ùn tắc.", "A2": "Người nghèo mất sinh kế."}, "Lợi ích lớn hơn.",
                          {"A1": UH, "A2": PD, "weighing": UH}, "side_flip"),
            {"attempt": 2, "purpose": "stance_review", "reviewer_verdict": "side_flip", "raw_output": "{}"},
            _plan_attempt(3, {"A1": "Giảm ùn tắc.", "A2": "Không khí sạch hơn."}, "Lợi ích lớn hơn.",
                          {"A1": UH, "A2": UH, "weighing": UH}, "pass"),
        ]),
        # lan chay 1 (con): pass, reviewer danh A3 khong ro
        _record(1, "M07", "con", "medium", [
            _plan_attempt(1, {"A1": "Người nghèo mất sinh kế.", "A2": "Hạ tầng thay thế chưa đủ.", "A3": "Khó thực thi."},
                          "Tác hại lớn hơn.", {"A1": PD, "A2": PD, "A3": KR, "weighing": PD}, "unclear"),
        ]),
        # lan chay 2: reviewer loi (khong co positions) -> khong lay mau
        _record(2, "M08", "pro", "hard", [
            {"attempt": 1, "purpose": "case_plan", "reviewer_verdict": "unclear", "raw_output": _case({"A1": "x"}, "w"),
             "reviewer_detail": {"reviewer_error": "loi"}},
        ]),
    ]
    path = tmp_path / "batch_v4.jsonl"
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records), encoding="utf-8")
    return path


# ---------------- label_stance ----------------


def test_pool_uses_attempts_not_only_final_case_file(batch_file):
    pool = ls.build_pool(load_jsonl(batch_file))
    assert sorted(pool) == ["batch_v4.jsonl:0:1", "batch_v4.jsonl:0:3", "batch_v4.jsonl:1:1"]
    assert pool["batch_v4.jsonl:0:1"]["reviewer_verdict"] == "side_flip"  # lan thu bi reject van co mat


def test_include_picks_side_flip_attempt(batch_file):
    [sample] = ls.resolve_include(f"{batch_file}:M07:pro:easy")
    assert sample["sample_id"] == "batch_v4.jsonl:0:1"
    with pytest.raises(ValueError, match="side_flip"):
        ls.resolve_include(f"{batch_file}:M07:con:medium")  # lan chay nay khong co side_flip
    with pytest.raises(ValueError, match="Khong thay"):
        ls.resolve_include(f"{batch_file}:M99:pro:easy")


def test_select_samples_is_deterministic_and_keeps_includes(batch_file):
    pool = ls.build_pool(load_jsonl(batch_file))
    includes = ls.resolve_include(f"{batch_file}:M07:pro:easy")
    first = [s["sample_id"] for s in ls.select_samples(pool, 1, 7, includes)]
    again = [s["sample_id"] for s in ls.select_samples(pool, 1, 7, includes)]
    assert first == again and len(first) == 2 and "batch_v4.jsonl:0:1" in first


def test_labeling_output_is_blind(batch_file, tmp_path):
    samples = list(ls.build_pool(load_jsonl(batch_file)).values())
    answers = iter("u p u " "u u u " "p p k p".split())
    printed: list[str] = []

    finished = ls.label_samples(samples, tmp_path / "labels.csv", input_fn=lambda prompt: (printed.append(prompt), next(answers))[1], out=printed.append)

    assert finished
    text = "\n".join(printed)
    for leak in (REVIEWER_MARK, "side_flip", "unclear", "reviewer", "ai_side", UH, PD, "easy", "medium", "hard"):
        assert leak not in text, leak
    assert not re.search(r"\b(pro|con)\b", text)
    assert "Nên cấm xe máy ở nội thành" in text and "[A1] Giảm ùn tắc." in text and "[weighing]" in text
    assert "…" in text  # reasoning dai bi rut gon


def test_resume_skips_labeled_samples(batch_file, tmp_path):
    samples = list(ls.build_pool(load_jsonl(batch_file)).values())
    labels = tmp_path / "labels.csv"
    answers = iter(["u", "p", "u", "u", "q"])  # xong mau 1 (3 muc), dung giua mau 2

    assert ls.label_samples(samples, labels, input_fn=lambda _: next(answers), out=lambda _: None) is False
    assert {r["sample_id"] for r in read_csv(labels)} == {samples[0]["sample_id"]}  # mau dang do KHONG luu

    asked: list[str] = []
    answers2 = iter("u u u p p k p".split())
    assert ls.label_samples(samples, labels, input_fn=lambda p: (asked.append(p), next(answers2))[1], out=lambda _: None)
    assert len(asked) == 7  # chi mau 2 (3 muc) + mau 3 (4 muc)
    assert len({r["sample_id"] for r in read_csv(labels)}) == 3


def test_invalid_answer_is_asked_again(batch_file, tmp_path):
    samples = list(ls.build_pool(load_jsonl(batch_file)).values())[:1]
    answers = iter(["x", "", "u", "p", "u"])
    assert ls.label_samples(samples, tmp_path / "l.csv", input_fn=lambda _: next(answers), out=lambda _: None)
    assert [r["human_label"] for r in read_csv(tmp_path / "l.csv")] == ["u", "p", "u"]


def test_report_agreement_confusion_flips_and_disagreements(batch_file, tmp_path):
    samples = ls.build_pool(load_jsonl(batch_file))
    order = ["batch_v4.jsonl:0:1", "batch_v4.jsonl:0:3", "batch_v4.jsonl:1:1"]
    labels = tmp_path / "labels.csv"
    # mau 0:1 (pro): nguoi dong y reviewer A2 lat phe (p); mau 0:3 (pro): nguoi danh A2 khong ro (reviewer u)
    # mau 1:1 (con): nguoi danh A3 = p (reviewer k), A1 = u (reviewer p -> bat dong, nguoi thay lat phe)
    answers = iter("u p u " "u k u " "u p p p".split())
    ls.label_samples([samples[s] for s in order], labels, input_fn=lambda _: next(answers), out=lambda _: None)

    report = ls.build_report(read_csv(labels), samples)

    assert report["items"] == 10 and report["compared"] == 10
    assert report["agree"] == 7  # bat dong: 0:3 A2 (k vs u), 1:1 A1 (u vs p), 1:1 A3 (p vs k)
    assert report["confusion"][("u", "u")] == 4 and report["confusion"][("p", "p")] == 3
    assert report["confusion"][("k", "u")] == 1 and report["confusion"][("u", "p")] == 1 and report["confusion"][("p", "k")] == 1
    flips = {(f["sample_id"], f["item_id"]) for f in report["human_flips"]}
    assert flips == {("batch_v4.jsonl:0:1", "A2"), ("batch_v4.jsonl:1:1", "A1")}
    reasons = {(d["sample_id"], d["item_id"]): d["reason"] for d in report["disagreements"]}
    assert reasons[("batch_v4.jsonl:1:1", "A1")] == f"{REVIEWER_MARK} A1"
    # ket luan theo mau: nguoi va reviewer cung side_flip o mau 0:1
    assert report["verdict_pairs"][("side_flip", "side_flip")] == 1  # 0:1: ca 2 thay A2 lat phe
    assert report["verdict_pairs"][("side_flip", "unclear")] == 1  # 1:1: nguoi thay A1 lat phe, reviewer chi "khong ro"
    text = ls.format_report(report)
    assert "7/10 (70%)" in text and REVIEWER_MARK in text  # reason CHI hien o report


def test_report_from_csv_reloads_sources(batch_file, tmp_path):
    samples = list(ls.build_pool(load_jsonl(batch_file)).values())[:1]
    labels = tmp_path / "labels.csv"
    answers = iter(["u", "u", "u"])
    ls.label_samples(samples, labels, input_fn=lambda _: next(answers), out=lambda _: None)
    assert "Nguoi vs reviewer" in ls.report_from_csv(labels)


# ---------------- label_vague_evidence ----------------


@pytest.fixture
def vague_file(tmp_path):
    case = {
        "motion_interpretation": "M.",
        "arguments": [{"id": "A1", "reasoning": "Câu đầu. Theo thống kê, 70% học sinh thiếu ngủ. Câu cuối."}],
        "anticipated_opponent_arguments": [{"id": "O1", "learner_claim": "Nhiều quốc gia đã áp dụng thuế này."}],
        "weighing": "Phe phản đối thắng khi chứng minh rằng thiệt hại lớn hơn.",
    }
    raw = json.dumps(case, ensure_ascii=False)
    records = [
        {"run_index": 0, "motion_id": "M10", "attempts": [{
            "attempt": 1, "purpose": "case_plan", "raw_output": raw,
            "vague_evidence": [
                {"phrase": "thống kê", "field": "arguments[0].reasoning"},
                {"phrase": "%", "field": "arguments[0].reasoning"},
                {"phrase": "nhiều quốc gia", "field": "anticipated_opponent_arguments[0].learner_claim"},
                {"phrase": "chứng minh", "field": "weighing"},
            ],
        }]},
        {"run_index": 1, "motion_id": "M11", "attempts": [{
            "attempt": 1, "purpose": "case_plan", "raw_output": raw, "vague_evidence": ["thống kê"],  # dang cu
        }]},
    ]
    path = tmp_path / "v.jsonl"
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records), encoding="utf-8")
    return path


def test_hits_show_phrase_field_and_sentence(vague_file):
    hits = lv.build_hits(load_jsonl(vague_file))
    assert len(hits) == 5
    first = hits[0]
    assert (first["phrase"], first["field"], first["group"]) == ("thống kê", "arguments[0].reasoning", "ai_fields")
    assert first["sentence"] == "Theo thống kê, 70% học sinh thiếu ngủ."
    assert hits[2]["group"] == "learner_claim"
    old = hits[4]
    assert old["group"] == "unknown" and old["shown_field"] == "arguments[0].reasoning (suy ra, du lieu cu)"
    assert old["sentence"] == "Theo thống kê, 70% học sinh thiếu ngủ."


def test_vague_labeling_resume_and_report_precision(vague_file, tmp_path):
    hits = lv.build_hits(load_jsonl(vague_file))
    labels = tmp_path / "vague.csv"
    shown: list[str] = []

    assert lv.label_hits(hits, labels, input_fn=lambda _, it=iter(["a", "a", "q"]): next(it), out=shown.append) is False
    assert "Cau    : Theo thống kê, 70% học sinh thiếu ngủ." in shown
    assert len(read_csv(labels)) == 2

    asked: list[str] = []
    answers = iter(["l", "zz", "n", "s"])
    assert lv.label_hits(hits, labels, input_fn=lambda p: (asked.append(p), next(answers))[1], out=lambda _: None)
    assert len(asked) == 4  # 3 hit con lai + 1 lan hoi lai vi "zz"

    report = lv.build_report(read_csv(labels))
    assert report["skipped"] == 1
    assert report["overall"] == {"total": 4, "a": 2, "l": 1, "n": 1, "precision": round(2 / 3, 3)}
    assert report["by_group"]["learner_claim"] == {"total": 1, "a": 0, "l": 1, "n": 0, "precision": None}
    assert report["by_group"]["ai_fields"]["precision"] == round(2 / 3, 3)  # a,a (reasoning) + n (weighing)
    assert report["by_phrase"]["chứng minh"] == {"total": 1, "a": 0, "l": 0, "n": 1, "precision": 0.0}
    assert "unknown" in report["by_group"] and report["by_group"]["unknown"]["total"] == 0  # hit cu bi bo qua (s)
    assert "precision=67%" in lv.format_report(report)
