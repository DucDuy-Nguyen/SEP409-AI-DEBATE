"""
Thi nghiem motion_type (dev log muc 2.13): API + DB, case_plan_v6 (A/B voi v5), motions_v2.json, batch runner, so sanh
theo motion_type, cong cu gan nhan mu label_case_structure. LLM gia.
"""
import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.main import app
from app.opponent.models import (
    DebateSide,
    LLMCallPurpose,
    MotionType,
    OpponentCaseFile,
    OpponentDifficulty,
    OpponentLLMCall,
    OpponentSession,
)
from app.opponent.prompts import case_plan_v3, case_plan_v5, case_plan_v6
from app.opponent.service import generate_case_file
from scripts import label_case_structure as lcs
from scripts.compare_case_plan_batches import compare, format_type_table
from scripts.eval_common import load_jsonl
from scripts.run_case_plan_batch import build_runs, draft_motions, load_motions, run_batch
from tests.conftest import VALID_CASE_FILE, FakeLLMClient

ROOT = Path(__file__).resolve().parent.parent
MOTIONS_V2 = ROOT / "experiments" / "motions_v2.json"
READING = "Cấm học sinh sử dụng điện thoại di động trong toàn bộ thời gian ở trường, kể cả giờ ra chơi, trừ trường hợp khẩn cấp được giáo viên cho phép."
V6 = Settings(_env_file=None, case_plan_prompt_version="case_plan_v6")
PRO, CON = DebateSide.PRO, DebateSide.CON


def _payload(**overrides) -> dict:
    return {"external_session_id": f"main-{uuid.uuid4()}", "motion": "Nên cấm học sinh sử dụng điện thoại trong trường học",
            "learner_side": "pro", "ai_side": "con", "difficulty": "medium"} | overrides


# ---------------- API + DB ----------------


async def test_without_motion_spec_old_behavior(client, db_session, fake_llm):
    fake_llm.responses = [json.dumps(VALID_CASE_FILE)]
    resp = await client.post("/opponent/sessions", json=_payload())
    assert resp.status_code == 201
    row = await db_session.get(OpponentSession, uuid.UUID(resp.json()["opponent_session_id"]))
    assert row.motion_type is None and row.motion_reading_provided is None
    case = await db_session.scalar(select(OpponentCaseFile).where(OpponentCaseFile.session_id == row.id))
    assert case.prompt_version == "case_plan_v5"


@pytest.mark.parametrize("extra", [{"motion_type": "policy"}, {"motion_reading": READING},
                                   {"motion_type": "value", "motion_reading": "   "}])
async def test_only_one_of_type_and_reading_is_400(client, fake_llm, extra):
    resp = await client.post("/opponent/sessions", json=_payload(**extra))
    assert resp.status_code == 400 and "cung nhau" in resp.json()["detail"]
    assert fake_llm.calls == []


async def test_invalid_motion_type_is_422(client):
    assert (await client.post("/opponent/sessions", json=_payload(motion_type="xyz", motion_reading=READING))).status_code == 422


async def test_spec_stored_and_part_of_idempotency(client, db_session, fake_llm):
    fake_llm.responses = [json.dumps(VALID_CASE_FILE)]
    payload = _payload(motion_type="policy", motion_reading=READING)
    first = await client.post("/opponent/sessions", json=payload)
    assert first.status_code == 201
    row = await db_session.get(OpponentSession, uuid.UUID(first.json()["opponent_session_id"]))
    assert (row.motion_type, row.motion_reading_provided) == (MotionType.POLICY, READING)

    assert (await client.post("/opponent/sessions", json=payload)).status_code == 200
    other_type = await client.post("/opponent/sessions", json={**payload, "motion_type": "value"})
    assert other_type.status_code == 409 and "motion_type" in other_type.json()["detail"]
    other_reading = await client.post("/opponent/sessions", json={**payload, "motion_reading": READING + " Sửa."})
    assert other_reading.status_code == 409 and "motion_reading" in other_reading.json()["detail"]
    dropped = {k: v for k, v in payload.items() if k not in ("motion_type", "motion_reading")}
    assert (await client.post("/opponent/sessions", json=dropped)).status_code == 409  # bo ca hai = du lieu khac
    assert len(fake_llm.calls) == 1
    got = (await client.get(f"/opponent/sessions/{payload['external_session_id']}")).json()
    assert (got["motion_type"], got["motion_reading_provided"]) == ("policy", READING)


async def test_v6_uses_reading_and_overrides_case_file(client, db_session, fake_llm):
    app.dependency_overrides[get_settings] = lambda: V6
    model_case = {**VALID_CASE_FILE, "motion_reading": "Model tự diễn giải: chỉ cấm trong giờ học."}
    fake_llm.responses = [json.dumps(model_case, ensure_ascii=False)]
    resp = await client.post("/opponent/sessions", json=_payload(motion_type="policy", motion_reading=READING))
    assert resp.status_code == 201, resp.text

    system = fake_llm.calls[0]["system"]
    assert f"1. Cách hiểu kiến nghị trong trận này (đã được ban tổ chức duyệt, dùng nguyên văn, không diễn giải lại): '{READING}'." in system
    assert case_plan_v6.MOTION_TYPE_MODULE[MotionType.POLICY] in system
    sid = uuid.UUID(resp.json()["opponent_session_id"])
    case = await db_session.scalar(select(OpponentCaseFile).where(OpponentCaseFile.session_id == sid))
    assert case.prompt_version == "case_plan_v6"
    assert case.content["motion_reading"] == READING  # GHI DE bat ke model tra gi
    plan = await db_session.scalar(select(OpponentLLMCall).where(
        OpponentLLMCall.session_id == sid, OpponentLLMCall.purpose == LLMCallPurpose.CASE_PLAN))
    assert plan.key_repairs == {"motion_reading_overridden": {"model": "Model tự diễn giải: chỉ cấm trong giờ học."}}


async def test_v6_same_reading_not_logged_and_v6_without_spec_falls_back_to_v5():
    same = {**VALID_CASE_FILE, "motion_reading": READING}
    out = await generate_case_file("M", CON, PRO, OpponentDifficulty.MEDIUM, FakeLLMClient([json.dumps(same)]), V6,
                                   motion_type=MotionType.VALUE, motion_reading=READING)
    assert out.prompt_version == "case_plan_v6" and out.case_file.motion_reading == READING
    assert out.attempts[0].key_repairs is None

    fake = FakeLLMClient([json.dumps(VALID_CASE_FILE)])
    out = await generate_case_file("M", CON, PRO, OpponentDifficulty.MEDIUM, fake, V6)  # thieu spec
    assert out.prompt_version == "case_plan_v5"
    assert fake.calls[0]["system"] == case_plan_v5.build_case_plan_prompt("M", CON, PRO, OpponentDifficulty.MEDIUM)[0]


async def test_v5_ignores_spec_even_if_given():
    fake = FakeLLMClient([json.dumps(VALID_CASE_FILE)])
    out = await generate_case_file("M", CON, PRO, OpponentDifficulty.MEDIUM, fake, Settings(_env_file=None),
                                   motion_type=MotionType.POLICY, motion_reading=READING)
    assert out.prompt_version == "case_plan_v5" and READING not in fake.calls[0]["system"] + fake.calls[0]["user"]
    assert out.case_file.motion_reading == VALID_CASE_FILE["motion_reading"]  # khong ghi de


# ---------------- prompt v6 ----------------


@pytest.mark.parametrize("mtype", list(MotionType))
@pytest.mark.parametrize("side", [PRO, CON])
def test_v6_prompt_differs_from_v5_only_in_reading_and_type(mtype, side):
    learner = CON if side == PRO else PRO
    s5, u5 = case_plan_v5.build_case_plan_prompt("M", side, learner, OpponentDifficulty.HARD)
    s6, u6 = case_plan_v6.build_case_plan_prompt("M", side, learner, OpponentDifficulty.HARD, mtype, READING)
    rules5 = [l.split(". ", 1)[1] for l in s5.splitlines() if l[:1].isdigit()]
    rules6 = [l.split(". ", 1)[1] for l in s6.splitlines() if l[:1].isdigit()]
    assert rules6[2:] == rules5[1:]  # quy tac 2..13 cua v5 giu NGUYEN (thanh 3..14)
    assert rules6[1] == case_plan_v6.MOTION_TYPE_MODULE[mtype]  # dung 1 module
    assert sum(m in s6 for m in case_plan_v6.MOTION_TYPE_MODULE.values()) == 1
    assert rules6[0].startswith(f"Cách hiểu kiến nghị trong trận này (đã được ban tổ chức duyệt, dùng nguyên văn, "
                                f"không diễn giải lại): '{READING}'.")
    assert "Định nghĩa kiến nghị một cách công bằng" not in s6 and "Chấp nhận cách hiểu phổ biến" not in s6
    if side == PRO:  # 2 cau KHONG ve cach hieu cua quy tac 1 v5 duoc giu
        assert rules6[0].endswith("KHÔNG mô tả sai hiện trạng để làm lập luận của mình mạnh hơn. "
                                  "Nếu không chắc về một chi tiết thực tế, đừng nêu nó.")
    # user prompt: chi mo ta motion_reading trong mau JSON khac
    assert u6.replace(case_plan_v6._OUTPUT_EXAMPLE_V6["motion_reading"], case_plan_v3._OUTPUT_EXAMPLE["motion_reading"]) == u5


def test_type_modules_verbatim():
    m = case_plan_v6.MOTION_TYPE_MODULE
    assert m[MotionType.POLICY].startswith("Đây là kiến nghị CHÍNH SÁCH.") and m[MotionType.POLICY].endswith(
        "Mỗi phe có ít nhất một luận điểm về thực thi.")
    assert m[MotionType.COMPARATIVE].endswith("Phần cân nhắc phải so sánh trực tiếp hai lựa chọn theo cùng tiêu chí.")
    assert m[MotionType.VALUE].startswith("Đây là kiến nghị CÂN NHẮC/GIÁ TRỊ, không có chính sách cụ thể.")
    with pytest.raises(ValueError):
        case_plan_v6.build_case_plan_prompt("M", PRO, CON, OpponentDifficulty.EASY)


# ---------------- motions_v2 + batch ----------------


def test_motions_v2_balanced():
    # Noi dung cach hieu / trang thai duyet do NGUOI DUNG sua (khong khoa trong test) — chi kiem tra cau truc.
    raw = json.loads(MOTIONS_V2.read_text(encoding="utf-8"))["motions"]
    assert [m["id"] for m in raw] == ["P1", "P2", "P3", "P4", "C1", "C2", "C3", "C4", "V1", "V2", "V3", "V4"]
    assert [m["motion_type"] for m in raw] == ["policy"] * 4 + ["comparative"] * 4 + ["value"] * 4
    assert all(m["reading_status"] in ("draft", "approved") and m["text"] and m["motion_reading"] for m in raw)
    motions = load_motions(MOTIONS_V2)
    assert motions[4] == {"id": "C1", "motion": "Người trẻ nên ở lại quê hương lập nghiệp thay vì lên thành phố",
                          "motion_type": "comparative", "motion_reading": raw[4]["motion_reading"],
                          "burden_pro": None, "burden_con": None, "reading_status": raw[4]["reading_status"]}
    assert draft_motions(motions) == [m["id"] for m in raw if m["reading_status"] == "draft"]
    assert draft_motions(load_motions(ROOT / "experiments" / "motions_v1.json")) == []  # v1 khong co reading
    assert build_runs(motions)[0]["motion_type"] == "policy"


@pytest.mark.parametrize("version,sent", [("case_plan_v5", False), ("case_plan_v6", True)])
async def test_batch_records_motion_type_and_sends_spec_only_for_v6(tmp_path, version, sent):
    motions = [m | {"reading_status": "approved"} for m in load_motions(MOTIONS_V2)[:1]]
    runs = build_runs(motions)[:1]
    fake = FakeLLMClient([json.dumps(VALID_CASE_FILE)])
    out = tmp_path / "b.jsonl"
    [record] = await run_batch(runs, fake, None, Settings(_env_file=None, case_plan_prompt_version=version), out)
    assert record["motion_type"] == "policy" and record["motion_reading"] == READING
    assert record["motion_reading_sent"] == (READING if sent else None)
    assert (READING in fake.calls[0]["system"]) is sent
    assert record["prompt_version"] == version
    assert json.loads(out.read_text(encoding="utf-8"))["motion_type"] == "policy"


# ---------------- so sanh theo motion_type ----------------


def _rec(mid, mtype, side, status="ready", version="case_plan_v5", tokens_in=1000, latency=1000, run_index=0):
    return {
        "run_index": run_index, "motion_id": mid, "motion": f"motion {mid}", "ai_side": side, "difficulty": "easy",
        "motion_type": mtype, "prompt_version": version, "final_status": status, "total_latency_ms": latency,
        "final_vague_evidence": None, "rerun_of": None, "case_file": {"x": 1} if status == "ready" else None,
        "attempts": [{"attempt": 1, "purpose": "case_plan", "success": status == "ready", "failure_kind": None,
                      "reviewer_verdict": None, "schema_rejected": False, "tokens_in": tokens_in,
                      "rate_limit_wait_ms": None, "retry_feedback": None}],
    }


def test_type_table_splits_by_motion_type(tmp_path):
    a = [_rec("P1", "policy", "pro"), _rec("V1", "value", "pro", status="invalid_output", run_index=1)]
    b = [_rec("P1", "policy", "pro", version="case_plan_v6", tokens_in=1500),
         _rec("V1", "value", "pro", version="case_plan_v6", run_index=1)]
    table = format_type_table("v5", "v6", a, b)
    assert "policy" in table and "value" in table and "comparative" not in table
    rows = [[c.strip() for c in line.strip("|").split("|")] for line in table.splitlines() if line.startswith("| ")]
    assert ["policy", "tokens_in tb / lan chay", "1000", "1500", "+500"] in rows
    assert ["value", "Thanh cong", "0/1 (0%)", "1/1 (100%)", "+1"] in rows
    assert format_type_table("v5", "v6", [_rec("P1", None, "pro")], []) is None

    pa, pb = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    pa.write_text("\n".join(json.dumps(r) for r in a), encoding="utf-8")
    pb.write_text("\n".join(json.dumps(r) for r in b), encoding="utf-8")
    text = compare({"v5": [pa], "v6": [pb]})
    assert "Tach theo motion_type" in text and "tokens_in trung binh / lan chay" in text


# ---------------- label_case_structure ----------------


def _batch(tmp_path, name, version, model_reading=None):
    case = {**VALID_CASE_FILE, "motion_reading": READING if version == "case_plan_v6" else "Cách hiểu của model."}
    key_repairs = {"motion_reading_overridden": {"model": model_reading}} if model_reading else None
    records = []
    for i, (mid, mtype) in enumerate([("P1", "policy"), ("V1", "value"), ("C1", "comparative")]):
        records.append({
            "run_index": i, "motion_id": mid, "motion": f"Kiến nghị {mid}", "motion_type": mtype,
            "motion_reading": READING, "prompt_version": version, "final_status": "ready", "case_file": case,
            "attempts": [{"attempt": 1, "purpose": "case_plan", "success": True, "key_repairs": key_repairs}],
        })
    records.append({"run_index": 9, "motion_id": "P2", "motion": "x", "motion_type": "policy",
                    "prompt_version": version, "final_status": "invalid_output", "case_file": None, "attempts": []})
    path = tmp_path / name
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records), encoding="utf-8")
    return path


def _samples(tmp_path):
    p5 = _batch(tmp_path, "20261001_case_plan_v5.jsonl", "case_plan_v5")
    p6 = _batch(tmp_path, "20261001_case_plan_v6.jsonl", "case_plan_v6", model_reading="Model tự viết khác.")
    canonical = {"P1": "CHUAN P1", "V1": "CHUAN V1", "C1": "CHUAN C1"}
    return lcs.build_samples(load_jsonl(p5) + load_jsonl(p6), canonical)


def test_q2_pass_is_blind_no_case_file_reading(tmp_path):
    samples = _samples(tmp_path)
    assert len(samples) == 6  # bo lan chay khong ready
    v6_p1 = next(s for s in samples if s["sample_id"] == "20261001_case_plan_v6.jsonl:0")
    assert v6_p1["model_reading"] == "Model tự viết khác."  # co trong mau nhung KHONG hien o luot Q2
    for s in samples:
        text = lcs.render_q2(s, 1, 6)
        # khong motion_reading cua case file: ban v5 cua model, ban v6 model tu viet, ban v6 da ghi de (= READING)
        for leak in ("Cách hiểu của model.", "Model tự viết khác.", READING, "MODEL viet"):
            assert leak not in text
        for leak in ("case_plan", "v5", "v6", "20261001", "prompt_version", "ai_side", "difficulty"):
            assert leak not in text.lower()
        assert f"Cach hieu CHUAN: {s['canonical_reading']}" in text and f"Loai: {s['motion_type']}" in text
    order = [s["sample_id"] for s in lcs.shuffle(samples, 7)]
    assert order == [s["sample_id"] for s in lcs.shuffle(list(reversed(samples)), 7)]  # xao tron on dinh theo seed
    assert order != sorted(order)


def test_q2_pass_all_samples_resume_and_skip_untyped(tmp_path):
    samples = lcs.shuffle(_samples(tmp_path), 1)
    untyped = {**samples[0], "sample_id": "x:99", "motion_type": None}
    labels = tmp_path / "q2.csv"
    answers = iter(["x", "y", "q"])  # mau 1: nhap sai roi y; mau 2: dung
    printed: list[str] = []
    assert lcs.label_q2([*samples, untyped], labels, input_fn=lambda _: next(answers), out=printed.append) is False
    rows = lcs.read_csv(labels)
    assert len(rows) == 1 and rows[0]["q2_structure"] == "y" and set(rows[0]) == set(lcs.Q2_FIELDS)
    assert any("Chi nhan" in line for line in printed) and any("Bo qua 1 mau" in line for line in printed)
    rest = iter(["n"] * 5)
    assert lcs.label_q2(samples, labels, input_fn=lambda _: next(rest), out=lambda _: None) is True
    rows = lcs.read_csv(labels)
    assert len(rows) == 6 and len({r["sample_id"] for r in rows}) == 6  # ca v5 va v6, chay tiep khong gan lai
    assert {r["sample_id"].split(":")[0] for r in rows} == {"20261001_case_plan_v5.jsonl", "20261001_case_plan_v6.jsonl"}


def test_q1_pass_only_v5_shows_model_reading(tmp_path):
    samples = lcs.shuffle(_samples(tmp_path), 3)
    labels = tmp_path / "q1.csv"
    shown: list[str] = []
    answers = iter(["g", "h", "k"])
    assert lcs.label_q1(samples, labels, input_fn=lambda _: next(answers), out=shown.append) is True
    rows = lcs.read_csv(labels)
    assert len(rows) == 3 and all(r["sample_id"].startswith("20261001_case_plan_v5.jsonl") for r in rows)
    assert set(rows[0]) == set(lcs.Q1_FIELDS)
    rendered = "\n".join(shown)
    assert "Cach hieu MODEL viet: Cách hiểu của model." in rendered and "Model tự viết khác." not in rendered
    assert "KHONG MU" in rendered


def test_report_q2_by_branch_type_total_and_q1_v5_only(tmp_path):
    samples = _samples(tmp_path)
    q2, q1 = tmp_path / "q2.csv", tmp_path / "q1.csv"
    for s in samples:  # v6: moi mau y; v5: chi policy y
        yes = s["prompt_version"] == "case_plan_v6" or s["motion_type"] == "policy"
        lcs.append_csv(q2, lcs.Q2_FIELDS, [lcs._row(s, q2_structure="y" if yes else "n")])
    for s in samples:  # co ca dong Q1 cho mau v6 (vd gan nham) -> bi loai khoi bao cao
        lcs.append_csv(q1, lcs.Q1_FIELDS, [lcs._row(s, q1_reading="h" if s["motion_type"] == "value" else "g")])

    report = lcs.report_from_csv(q2, q1)
    assert "case_plan_v5 x policy | 1 | 1/1 (100%)" in report
    assert "case_plan_v5 x value | 1 | 0/1 (0%)" in report
    assert "case_plan_v5 x tat ca | 3 | 1/3 (33%)" in report
    assert "case_plan_v6 x tat ca | 3 | 3/3 (100%)" in report
    q1_part = report.split("Q1 (KHONG MU")[1]
    assert "case_plan_v5 x tat ca | 3 | 2 / 1 / 0 / 0" in q1_part  # CHI 3 mau v5
    assert "case_plan_v6" not in q1_part
    assert lcs.report_from_csv(tmp_path / "none.csv", tmp_path / "none1.csv").startswith("Chua co nhan nao")


async def test_batch_main_refuses_draft_readings(monkeypatch, capsys, tmp_path):
    from scripts import run_case_plan_batch as rb

    raw = json.loads(MOTIONS_V2.read_text(encoding="utf-8"))
    raw["motions"][3]["reading_status"] = "draft"  # file tam: 1 motion chua duyet
    draft_file = tmp_path / "motions_draft.json"
    draft_file.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    out_dir = tmp_path / "out"
    monkeypatch.setattr("sys.argv", ["run_case_plan_batch", "--motions", str(draft_file), "--prompt-version", "v6",
                                     "--out-dir", str(out_dir)])
    monkeypatch.setattr(rb, "get_llm_client", lambda *a, **k: pytest.fail("khong duoc tao LLM client"))
    assert await rb.main() == 2
    assert 'con o trang thai "draft" hoac con gia tri giu cho (P4)' in capsys.readouterr().out
    assert not out_dir.exists()
