"""
scripts/replay_stance_review.py voi reviewer GIA (khong goi LLM that): tim file nhan, nap mau, chay lai, bao cao,
so sanh v1 / v2.
"""
import csv
import json

import pytest

from app.core.config import Settings
from scripts import replay_stance_review as rp
from tests.conftest import FakeStanceReviewer, RateLimited

UH, PD, KR = "ung_ho_kien_nghi", "phan_doi_kien_nghi", "khong_ro"
M10_FILE = "20260927-094713_case_plan_v4.jsonl"  # ten that -> khop SPECIAL_CASES
M08_FILE = "20260926-171443_case_plan_v3.jsonl"


def _attempt(n, claims: dict, weighing, original: dict, verdict):
    case = {
        "motion_reading": "M.", "definitions": [], "anticipated_opponent_arguments": [], "weighing": weighing,
        "arguments": [{"id": i, "title": "t", "claim": c, "reasoning": f"Lý do của {i}.", "example": "Giả sử...", "impact": "x"}
                      for i, c in claims.items()],
    }
    return {"attempt": n, "purpose": "case_plan", "raw_output": json.dumps(case, ensure_ascii=False),
            "reviewer_verdict": verdict,
            "reviewer_detail": {"positions": [{"id": i, "position": p, "reason": "r"} for i, p in original.items()]}}


def _write_jsonl(path, records):
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records), encoding="utf-8")


def _write_labels(path, rows):
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["sample_id", "source_path", "run_index", "attempt", "motion_id", "item_id",
                                          "human_label", "labeled_at"])
        w.writeheader()
        w.writerows(rows)


def _rows(sample_id, source_path, labels: dict):
    file_name, run, attempt = sample_id.rsplit(":", 2)
    return [{"sample_id": sample_id, "source_path": str(source_path), "run_index": run, "attempt": attempt,
             "motion_id": "M", "item_id": k, "human_label": v, "labeled_at": "t"} for k, v in labels.items()]


@pytest.fixture
def dataset(tmp_path):
    cases = tmp_path / "case_plan"
    cases.mkdir()
    m10 = cases / M10_FILE
    _write_jsonl(m10, [{"run_index": 19, "motion_id": "M10", "motion": "Nên đánh thuế cao đối với đồ uống có đường",
                        "ai_side": "con", "difficulty": "medium", "attempts": [
                            _attempt(1, {"A1": "Tăng chi phí.", "A3": "Giá tăng do thuế không chắc chắn dẫn đến giảm tiêu thụ."},
                                     "Phe phản đối thắng.", {"A1": PD, "A3": UH, "weighing": PD}, "side_flip")]}])
    m08 = cases / M08_FILE
    _write_jsonl(m08, [{"run_index": 15, "motion_id": "M08", "motion": "Nên dùng AI chấm bài thi", "ai_side": "con",
                        "difficulty": "easy", "attempts": [
                            _attempt(3, {"A1": "AI giảm lỗi chấm.", "A2": "AI không đánh giá được sáng tạo."},
                                     "Phe phản đối mạnh hơn.", {"A1": UH, "A2": PD, "weighing": PD}, "side_flip")]}])
    other = cases / "x_v3.jsonl"
    _write_jsonl(other, [{"run_index": 0, "motion_id": "M01", "motion": "Nên cấm điện thoại", "ai_side": "pro",
                          "difficulty": "easy", "attempts": [
                              _attempt(1, {"A1": "Giảm xao nhãng.", "A2": "Tăng giao tiếp."}, "Lợi ích lớn.",
                                       {"A1": UH, "A2": UH, "weighing": UH}, "pass")]}])
    labels = tmp_path / "labels"
    labels.mkdir()
    _write_labels(labels / "stance_labels.csv",  # dot 1: weighing bi loai khi tinh dong thuan
                  _rows(f"{M10_FILE}:19:1", m10, {"A1": "p", "A3": "p", "weighing": "k"})
                  + _rows(f"{M08_FILE}:15:3", m08, {"A1": "u", "A2": "p", "weighing": "k"}))
    _write_labels(labels / "stance_labels_round2.csv", _rows("x_v3.jsonl:0:1", other, {"A1": "u", "A2": "u", "weighing": "u"}))
    _write_labels(labels / "stance_labels_round2_old.csv", _rows("x_v3.jsonl:0:1", other, {"A1": "p"}))  # bo qua
    return labels


def test_find_label_files_prefers_current_names_and_skips_old(dataset):
    files = rp.find_label_files(dataset)
    assert {k: v.name for k, v in files.items()} == {1: "stance_labels.csv", 2: "stance_labels_round2.csv"}


def test_find_label_files_includes_v5_labels_as_round3(dataset):
    _write_labels(dataset / "stance_labels_v5.csv", [])
    _write_labels(dataset / "stance_labels_v5_old.csv", [])
    assert rp.find_label_files(dataset)[3].name == "stance_labels_v5.csv"


def test_find_label_files_finds_renamed_round1(dataset):
    (dataset / "stance_labels.csv").rename(dataset / "stance_labels_round1.csv")
    assert rp.find_label_files(dataset)[1].name == "stance_labels_round1.csv"


def test_load_labeled_samples(dataset):
    samples = {s["sample_id"]: s for s in rp.load_labeled_samples(rp.find_label_files(dataset))}
    m10 = samples[f"{M10_FILE}:19:1"]
    assert m10["round"] == 1 and m10["ai_side"] == "con" and m10["human"] == {"A1": "p", "A3": "p", "weighing": "k"}
    assert m10["arguments"][1] == {"id": "A3", "claim": "Giá tăng do thuế không chắc chắn dẫn đến giảm tiêu thụ.",
                                   "reasoning": "Lý do của A3."}
    assert m10["original"]["A3"] == UH and m10["original_verdict"] == "side_flip"
    assert samples["x_v3.jsonl:0:1"]["round"] == 2 and samples["x_v3.jsonl:0:1"]["human"]["A1"] == "u"  # khong lay _old


def _replay(dataset, tmp_path, reviewer, version="stance_review_v2", **settings):
    samples = rp.load_labeled_samples(rp.find_label_files(dataset))
    slept: list[float] = []
    out = tmp_path / "replay" / f"x_{version}.jsonl"
    results = rp.replay(samples, reviewer, Settings(_env_file=None, **settings), version, out, pause=2,
                        sleep=slept.append, log=lambda _: None)
    return results, out, slept


def test_replay_writes_jsonl_uses_version_and_no_side(dataset, tmp_path):
    reviewer = FakeStanceReviewer(PD)
    reviewer.positions = {"A1": PD}
    results, out, slept = _replay(dataset, tmp_path, reviewer)

    lines = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines()]
    assert lines == results and len(lines) == 3
    assert all(r["reviewer_version"] == "stance_review_v2" and r["temperature"] == 0.0 for r in lines)
    assert slept == [2, 2]  # --pause giua cac loi goi
    m10_prompt = next(c["user"] for c in reviewer.calls if "không chắc chắn" in c["user"])
    assert 'Lý do: "Lý do của A3."' in m10_prompt  # v2 co reasoning
    assert all(c["temperature"] == 0.0 and c["json_schema"] for c in reviewer.calls)


def test_replay_prompt_does_not_depend_on_ai_side(dataset, tmp_path):
    # Dao phe cua moi mau -> prompt gui reviewer PHAI giong het: khong co thong tin phe nao lot vao.
    samples = rp.load_labeled_samples(rp.find_label_files(dataset))
    flipped = [{**s, "ai_side": "pro" if s["ai_side"] == "con" else "con"} for s in samples]
    calls = []
    for batch in (samples, flipped):
        reviewer = FakeStanceReviewer(PD)
        rp.replay(batch, reviewer, Settings(_env_file=None), "stance_review_v2", tmp_path / "p.jsonl",
                  sleep=lambda _: None, log=lambda _: None)
        calls.append([(c["system"], c["user"]) for c in reviewer.calls])
    assert calls[0] == calls[1]


def test_replay_v1_prompt_has_no_reasoning(dataset, tmp_path):
    reviewer = FakeStanceReviewer(PD)
    _replay(dataset, tmp_path, reviewer, version="stance_review_v1")
    assert all("Lý do của" not in c["user"] for c in reviewer.calls)


def test_replay_retries_429_and_records_errors(dataset, tmp_path):
    reviewer = FakeStanceReviewer(PD)
    reviewer.responses = [RateLimited("Please try again in 4s."), "khong phai json"]
    results, _, slept = _replay(dataset, tmp_path, reviewer)
    assert slept[0] == 5.0  # 4s provider yeu cau + 1s
    assert results[0]["error"] and results[0]["verdict"] is None  # mau 1: output sai -> ghi loi, chay tiep
    assert all(r["verdict"] for r in results[1:])


def test_report_separates_arguments_weighing_excludes_round1_weighing_and_lists_special(dataset, tmp_path):
    reviewer = FakeStanceReviewer(PD)
    reviewer.positions = {"A1": PD}  # M08 A1: nguoi u, reviewer p -> bat dong; x_v3 (pro): nguoi u, reviewer p
    results, _, _ = _replay(dataset, tmp_path, reviewer)

    report = rp.build_report(results)

    # luan diem: M10 A1 p/p, A3 p/p; M08 A1 u/p (x), A2 p/p; x_v3 A1 u/p (x), A2 u/p (x) -> 3/6
    assert report["arguments"] == (3, 6)
    assert report["weighing"] == (0, 1)  # chi weighing dot 2 (x_v3): nguoi u, reviewer p
    assert report["confusion"][("u", "p")] == 4 and report["confusion"][("p", "p")] == 3
    assert {s["sample_id"] for s in report["special"]} == set(rp.SPECIAL_CASES)
    text = rp.format_report(report)
    assert "luan diem: 3/6 (50%)" in text and "weighing (dot 2+): 0/1 (0%)" in text
    assert "M10 con medium v4 — lan thu #1" in text and "[A3] nguoi=phan doi | batch=u | replay=p" in text


def test_compare_lists_changed_items(dataset, tmp_path):
    v1 = FakeStanceReviewer(PD)
    v1.positions = {"A3": UH}  # v1 dao nghia phu dinh o M10 A3
    v2 = FakeStanceReviewer(PD)
    a, _, _ = _replay(dataset, tmp_path, v1, version="stance_review_v1")
    b, _, _ = _replay(dataset, tmp_path, v2, version="stance_review_v2")

    text = rp.compare_replays(a, b)

    assert f"{M10_FILE}:19:1 verdict: side_flip -> pass" in text
    assert f"{M10_FILE}:19:1 [A3] u -> p | nguoi=p" in text
    assert text.count(" -> ") == 2  # chi A3 + verdict cua M10 doi



def test_replay_v3_records_restatements_tokens_and_max_tokens(dataset, tmp_path):
    reviewer = FakeStanceReviewer(PD)
    results, out, _ = _replay(dataset, tmp_path, reviewer, version="stance_review_v3")

    m10 = next(r for r in results if r["sample_id"] == f"{M10_FILE}:19:1")
    assert m10["verdict"] == "pass" and m10["positions"]["A3"] == PD
    assert m10["restatements"]["A3"] == "dien dat lai A3"
    assert m10["max_tokens"] == 2000 and "tokens_out" in m10
    assert all('"restatement"' in json.dumps(c["json_schema"]) for c in reviewer.calls)
    text = rp.format_report(rp.build_report(results))
    assert "dien dat lai (v3): dien dat lai A3" in text and "(max_tokens=2000)" in text


def test_replay_versions_include_v3():
    assert rp.VERSIONS == {"v1": "stance_review_v1", "v2": "stance_review_v2", "v3": "stance_review_v3"}


# ---------------- che do --from-batch ----------------

BATCH_FILE = "20260929-163008_case_plan_v5.jsonl"
FEEDBACK = "[PHẢN HỒI LẦN THỬ TRƯỚC]\n- `weighing` đang bảo vệ phe Đề xuất."


def _batch_attempt(n, verdict, success, original, feedback=None):
    a = _attempt(n, {"A1": f"Luận điểm lần {n}."}, f"Cân nhắc lần {n}.", original, verdict)
    a.update(success=success, retry_feedback=feedback)
    a["reviewer_detail"]["prompt_version"] = "stance_review_v3"
    for p in a["reviewer_detail"]["positions"]:
        p["restatement"] = f"batch hieu {p['id']} lan {n}"
    return a


def _log(n):  # log rieng cua reviewer (purpose stance_review) — khong phai mau
    return {"attempt": n, "purpose": "stance_review", "raw_output": "{}", "success": True, "reviewer_verdict": "side_flip"}


def _rate_limited(n):
    return {"attempt": n, "purpose": "case_plan", "raw_output": None, "success": False, "reviewer_verdict": None}


@pytest.fixture
def batch(tmp_path):
    """Giong run 9 (M05 con easy) batch v5: #1, #4 side_flip -> #7 chap nhan; run khac: unclear -> chap nhan; run pass."""
    path = tmp_path / BATCH_FILE
    _write_jsonl(path, [
        {"run_index": 9, "motion_id": "M05", "motion": "Sinh viên nên đi làm thêm", "ai_side": "con",
         "difficulty": "easy", "attempts": [
             _batch_attempt(1, "side_flip", False, {"A1": PD, "weighing": UH}, FEEDBACK), _log(2), _rate_limited(3),
             _batch_attempt(4, "side_flip", False, {"A1": PD, "weighing": UH}, FEEDBACK), _log(5), _rate_limited(6),
             _batch_attempt(7, "pass", True, {"A1": PD, "weighing": PD}), _log(8)]},
        {"run_index": 3, "motion_id": "M02", "motion": "Nên học trực tuyến", "ai_side": "pro", "difficulty": "hard",
         "attempts": [_batch_attempt(1, "unclear", False, {"A1": KR, "weighing": UH}),
                      _batch_attempt(3, "pass", True, {"A1": UH, "weighing": UH})]},
        {"run_index": 4, "motion_id": "M03", "motion": "Nên cấm xe máy", "ai_side": "pro", "difficulty": "easy",
         "attempts": [_batch_attempt(1, "pass", True, {"A1": UH, "weighing": UH})]},
    ])
    labels = tmp_path / "labels"
    labels.mkdir()
    _write_labels(labels / "stance_labels_v5.csv", _rows(f"{BATCH_FILE}:9:1", path, {"A1": "p", "weighing": "p"}))
    _write_labels(labels / "stance_labels_v5_old.csv", _rows(f"{BATCH_FILE}:9:4", path, {"A1": "u"}))  # bo qua
    return path, labels


def test_load_batch_only_flagged_picks_flagged_and_next_accepted_once(batch):
    path, labels = batch
    samples = rp.load_batch_samples(path, only_flagged=True, human_labels=rp.load_human_labels(labels))

    got = [(s["sample_id"].split(":", 1)[1], s["role"]) for s in samples]
    assert got == [("9:1", "flagged"), ("9:7", "accepted_after"), ("9:4", "flagged"), ("3:1", "flagged"),
                   ("3:3", "accepted_after")]  # #7 chi 1 lan; bo stance_review, rate_limited, run chi co pass
    by_id = {s["sample_id"]: s for s in samples}
    first = by_id[f"{BATCH_FILE}:9:1"]
    assert first["human"] == {"A1": "p", "weighing": "p"} and by_id[f"{BATCH_FILE}:9:4"]["human"] == {}  # _old bo qua
    assert first["original"] == {"A1": PD, "weighing": UH} and first["original_verdict"] == "side_flip"
    assert first["original_version"] == "stance_review_v3"
    assert first["original_restatements"]["weighing"] == "batch hieu weighing lan 1"
    assert first["retry_feedback"] == FEEDBACK and first["weighing"] == "Cân nhắc lần 1."


def test_load_batch_without_only_flagged_takes_every_reviewed_attempt(batch):
    path, _ = batch
    samples = rp.load_batch_samples(path, only_flagged=False)
    assert [s["sample_id"].split(":", 1)[1] for s in samples] == ["9:1", "9:4", "9:7", "3:1", "3:3", "4:1"]
    assert {s["role"] for s in samples} == {"reviewed"}


def test_batch_comparison_side_by_side_with_v3_restatement_and_human(batch, tmp_path):
    path, labels = batch
    samples = rp.load_batch_samples(path, only_flagged=True, human_labels=rp.load_human_labels(labels))
    reviewer = FakeStanceReviewer(PD)  # ai_side con: moi muc phan doi -> pass
    reviewer.positions = {"A1": UH}  # ... tru A1 -> side_flip o run 9; run 3 (pro): A1 ung ho, weighing phan doi
    results = rp.replay(samples, reviewer, Settings(_env_file=None), "stance_review_v3", tmp_path / "r.jsonl",
                        sleep=lambda _: None, log=lambda _: None)

    text = rp.format_batch_comparison(results)

    assert "BATCH vs REPLAY stance_review_v3 — 5 lan thu" in text
    assert "M05 con easy — run 9 lan thu #1 (BI BAO luc chay batch)" in text
    assert "M05 con easy — run 9 lan thu #7 (duoc chap nhan ngay sau)" in text
    assert "verdict: batch (stance_review_v3) = side_flip -> replay = side_flip" in text
    assert "=> [A1] batch=p replay=u nguoi=p" in text  # position doi -> danh dau "=>"
    assert "   [weighing] batch=u replay=p nguoi=p" not in text and "=> [weighing] batch=u replay=p nguoi=p" in text
    assert "dien dat lai (batch): batch hieu weighing lan 1" in text
    assert "dien dat lai (replay): dien dat lai weighing" in text
    assert "phan hoi retry generator da nhan: [PHẢN HỒI LẦN THỬ TRƯỚC] | - `weighing`" in text
    # run 9: #1, #4 side_flip -> side_flip (giu), #7 pass -> side_flip (doi); run 3: #1 unclear -> side_flip, #3 pass -> side_flip
    assert "Verdict doi so voi batch: 3/5" in text
    assert "Dong thuan voi nhan nguoi (moi muc co nhan): batch 1/2 | replay 1/2" in text


def test_main_from_batch_uses_fake_llm_and_writes_from_batch_file(batch, tmp_path, capsys):
    path, labels = batch
    out_dir = tmp_path / "out"
    reviewer = FakeStanceReviewer(PD)
    slept: list[float] = []
    code = rp.main(["--from-batch", str(path), "--only-flagged", "--reviewer-version", "v3", "--labels-dir", str(labels),
                    "--out-dir", str(out_dir), "--pause", "1"], client=reviewer, settings=Settings(_env_file=None),
                   sleep=slept.append)

    assert code == 0 and len(reviewer.calls) == 5 and slept == [1, 1, 1, 1]
    [out] = list(out_dir.glob("*_stance_review_v3_from-batch.jsonl"))
    lines = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines()]
    assert [r["role"] for r in lines] == ["flagged", "accepted_after", "flagged", "flagged", "accepted_after"]
    printed = capsys.readouterr().out
    assert f"5 mau tu {BATCH_FILE} (only-flagged) | stance_review_v3" in printed and "BATCH vs REPLAY" in printed
    assert "Hai ca dac biet" not in printed  # khong in phan special cases o che do batch


def test_main_only_flagged_requires_from_batch(capsys):
    with pytest.raises(SystemExit):
        rp.main(["--only-flagged"], client=FakeStanceReviewer(PD), settings=Settings(_env_file=None))
    assert "--only-flagged chi dung cung --from-batch" in capsys.readouterr().err
