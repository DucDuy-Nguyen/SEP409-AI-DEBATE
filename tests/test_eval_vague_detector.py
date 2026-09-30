"""
scripts/eval_vague_detector.py: ghep hit moi voi nhan cu, precision, chua co nhan, bo sot. Du lieu gia lap.
"""
import json

from scripts import eval_vague_detector as ev
from scripts.eval_common import load_jsonl


def _raw(**fields) -> str:
    base = {
        "motion_reading": "M.",
        "arguments": [
            {"id": "A1", "claim": "C1.", "reasoning": "R1.", "example": "Giả sử giá tăng 30%.", "impact": "I1."},
            {"id": "A2", "claim": "C2.", "reasoning": "R2.", "example": "Giả sử...", "impact": "I2."},
        ],
        "anticipated_opponent_arguments": [{"id": "O1", "learner_claim": "L.", "planned_response": "P."}],
        "weighing": "W.",
    }
    for path, text in fields.items():
        if "__" in path:
            name, idx, sub = path.split("__")
            base[name][int(idx)][sub] = text
        else:
            base[path] = text
    return json.dumps(base, ensure_ascii=False)


def _label(run, attempt, field, phrase, label, source="b.jsonl"):
    return {"hit_id": f"{source}:{run}:{attempt}:{field}:{phrase}", "source_path": f"experiments\\case_plan\\{source}",
            "run_index": str(run), "attempt": str(attempt), "field": field, "group": "ai_fields", "phrase": phrase,
            "label": label, "sentence": "..."}


def test_evaluate_matches_labels_counts_precision_unlabeled_and_missed(tmp_path):
    records = [
        {"run_index": 0, "motion_id": "M05", "attempts": [{
            "attempt": 1, "purpose": "case_plan", "vague_evidence": [],
            "raw_output": _raw(
                anticipated_opponent_arguments__0__planned_response="Một số nghiên cứu (không nêu cụ thể) cho thấy điều đó.",
                arguments__0__reasoning="Thời gian cho nghiên cứu giảm đi.",
                weighing="Nhiều sinh viên đã chứng minh khả năng làm thêm.",
            ),
        }]},
        {"run_index": 1, "motion_id": "M06", "attempts": [
            {"attempt": 1, "purpose": "case_plan", "vague_evidence": None, "raw_output": _raw(weighing="Chuyên gia cho rằng x.")},
            {"attempt": 2, "purpose": "case_plan", "vague_evidence": [],
             "raw_output": _raw(arguments__1__impact="Học sinh không có cơ hội chứng minh năng lực.",
                                weighing="Hiệu quả đã được chứng minh.")},
        ]},
    ]
    path = tmp_path / "b.jsonl"
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records), encoding="utf-8")
    labels = [
        _label(0, 1, "anticipated_opponent_arguments[0].planned_response", "nghiên cứu", "a"),
        _label(0, 1, "arguments[0].reasoning", "nghiên cứu", "n"),
        _label(0, 1, "arguments[0].example", "%", "n"),  # bo do moi khong quet % trong example
        _label(1, 2, "arguments[1].impact", "chứng minh", "n"),  # bo do moi khong bat
        _label(1, 2, "weighing", "chứng minh", "a"),
        _label(1, 2, "arguments[0].reasoning", "chứng minh", "a"),  # 'a' khong con hit -> bo sot
        _label(9, 1, "weighing", "%", "n", source="other.jsonl"),  # file khac -> bo qua
    ]

    result = ev.evaluate(load_jsonl(path), labels)

    assert result["old"] == {"hits": 6, "a": 3, "n": 3, "l": 0, "precision": (3, 6)}
    assert result["high"] == {"hits": 3, "a": 2, "n": 0, "l": 0, "unlabeled": 1, "conflict": 0, "precision": (2, 2)}
    assert result["low"]["hits"] == 1 and result["low"]["n"] == 1  # "nghiên cứu" thuong -> LOW, nhan n
    unlabeled = [h for h in result["hits"] if h["label"] == "?"]
    assert [(h["run_index"], h["field"], h["rule"]) for h in unlabeled] == [(0, "weighing", "nhieu_chu_the_da")]
    assert [row["field"] for row in result["missed"]] == ["arguments[0].reasoning"]
    # lan thu chua duoc bo do cu quet (vague_evidence None) -> khong danh gia
    assert all(h["attempt"] != 1 or h["run_index"] != 1 for h in result["hits"])

    text = ev.format_report("TAP KIEM TRA", result)
    assert "precision (tren hit da co nhan) 2/2 (100%)" in text
    assert "CHUA CO NHAN — can gan tay (1)" in text and "Nhiều sinh viên đã chứng minh" in text
    assert "BO SOT: nhan 'a' khong con hit HIGH nao (1)" in text
