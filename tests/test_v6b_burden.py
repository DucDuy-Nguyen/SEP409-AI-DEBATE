"""
Thi nghiem v6b — ganh nang chung minh (dev log muc 2.15): API + DB, case_plan_v6b, motions_v3.json, batch
(--prompt-version v6b, --only-failed loi ha tang / --include-content-failures), so sanh, ngu canh gan nhan. LLM gia.
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
from app.opponent.prompts import case_plan_v6, case_plan_v6b
from app.opponent.service import generate_case_file
from scripts import label_case_structure as lcs
from scripts.compare_case_plan_batches import compare, load_group
from scripts.run_case_plan_batch import build_runs, draft_motions, load_motions, run_batch, runs_from_failed
from tests.conftest import VALID_CASE_FILE, FakeLLMClient, make_case_file

EASY_CASE = json.dumps(make_case_file(2))  # do kho easy: dung 2 luan diem

ROOT = Path(__file__).resolve().parent.parent
MOTIONS_V2 = ROOT / "experiments" / "motions_v2.json"
MOTIONS_V3 = ROOT / "experiments" / "motions_v3.json"
BP = "Mạng xã hội gây hại cho người 15–24 tuổi nhiều hơn lợi ích nó mang lại."
BC = "Lợi ích của mạng xã hội với người 15–24 tuổi lớn hơn hoặc ngang với tác hại."
V6B = Settings(_env_file=None, case_plan_prompt_version="case_plan_v6b")
PRO, CON = DebateSide.PRO, DebateSide.CON


def _payload(**overrides) -> dict:
    return {"external_session_id": f"main-{uuid.uuid4()}", "motion": "Mạng xã hội gây hại nhiều hơn có lợi cho giới trẻ",
            "learner_side": "pro", "ai_side": "con", "difficulty": "medium"} | overrides


# ---------------- API + DB ----------------


@pytest.mark.parametrize("extra", [
    # (burden KHONG kem motion_type: hop le tu muc 2.16 — v7 khong can motion_type; xem tests/test_v7_burden.py)
    {"motion_type": "value", "burden_pro": BP},  # thieu burden_con
    {"motion_type": "value", "burden_con": BC},
    {"motion_type": "value"},  # motion_type mot minh
    {"motion_type": "value", "burden_pro": BP, "burden_con": "   "},  # rong = khong gui
])
async def test_burden_spec_must_be_complete_400(client, fake_llm, extra):
    resp = await client.post("/opponent/sessions", json=_payload(**extra))
    assert resp.status_code == 400 and "cung nhau" in resp.json()["detail"], resp.text
    assert fake_llm.calls == []


async def test_burdens_stored_and_part_of_idempotency(client, db_session, fake_llm):
    fake_llm.responses = [json.dumps(VALID_CASE_FILE)]
    payload = _payload(motion_type="value", burden_pro=BP, burden_con=BC)
    first = await client.post("/opponent/sessions", json=payload)
    assert first.status_code == 201, first.text
    row = await db_session.get(OpponentSession, uuid.UUID(first.json()["opponent_session_id"]))
    assert (row.motion_type, row.burden_pro, row.burden_con, row.motion_reading_provided) == (MotionType.VALUE, BP, BC, None)

    assert (await client.post("/opponent/sessions", json=payload)).status_code == 200
    for field in ("burden_pro", "burden_con"):
        other = await client.post("/opponent/sessions", json={**payload, field: "Khác."})
        assert other.status_code == 409 and field in other.json()["detail"]
    assert len(fake_llm.calls) == 1
    got = (await client.get(f"/opponent/sessions/{payload['external_session_id']}")).json()
    assert (got["burden_pro"], got["burden_con"]) == (BP, BC)


async def test_v6b_uses_burden_block_and_overrides_reading_with_ai_burden(client, db_session, fake_llm):
    app.dependency_overrides[get_settings] = lambda: V6B
    model_case = {**VALID_CASE_FILE, "motion_reading": "Cân nhắc tổng thể tác hại và lợi ích."}
    fake_llm.responses = [json.dumps(model_case, ensure_ascii=False)]
    payload = _payload(motion_type="value", burden_pro=BP, burden_con=BC)
    resp = await client.post("/opponent/sessions", json=payload)
    assert resp.status_code == 201, resp.text

    system = fake_llm.calls[0]["system"]
    assert (f"1. Kiến nghị: '{payload['motion']}'.\nPhe Đề xuất phải chứng minh: {BP}\nPhe Phản đối phải chứng minh: {BC}\n"
            f"BẠN là phe Phản đối. Mọi luận điểm và phần cân nhắc của bạn phải chứng minh: {BC}") in system
    assert case_plan_v6.MOTION_TYPE_MODULE[MotionType.VALUE] in system
    sid = uuid.UUID(resp.json()["opponent_session_id"])
    case = await db_session.scalar(select(OpponentCaseFile).where(OpponentCaseFile.session_id == sid))
    assert case.prompt_version == "case_plan_v6b"
    assert case.content["motion_reading"] == BC  # = burden cua phe AI (con)
    plan = await db_session.scalar(select(OpponentLLMCall).where(
        OpponentLLMCall.session_id == sid, OpponentLLMCall.purpose == LLMCallPurpose.CASE_PLAN))
    assert plan.key_repairs == {"motion_reading_overridden": {"model": "Cân nhắc tổng thể tác hại và lợi ích."}}


async def test_v6b_ai_pro_reading_is_burden_pro_and_fallbacks():
    out = await generate_case_file("M", PRO, CON, OpponentDifficulty.EASY, FakeLLMClient([EASY_CASE]),
                                   V6B, motion_type=MotionType.VALUE, burden_pro=BP, burden_con=BC)
    assert out.prompt_version == "case_plan_v6b" and out.case_file.motion_reading == BP
    # v6b thieu burden -> v5
    out = await generate_case_file("M", PRO, CON, OpponentDifficulty.EASY, FakeLLMClient([EASY_CASE]),
                                   V6B, motion_type=MotionType.VALUE, motion_reading="R")
    assert out.prompt_version == "case_plan_v5"
    # v6 voi chi burden (khong motion_reading) -> v5; v5 voi burden -> bo qua
    for version in ("case_plan_v6", "case_plan_v5"):
        fake = FakeLLMClient([EASY_CASE])
        out = await generate_case_file("M", PRO, CON, OpponentDifficulty.EASY, fake,
                                       Settings(_env_file=None, case_plan_prompt_version=version),
                                       motion_type=MotionType.VALUE, burden_pro=BP, burden_con=BC)
        assert out.prompt_version == "case_plan_v5" and BP not in fake.calls[0]["system"]


# ---------------- prompt ----------------


@pytest.mark.parametrize("mtype", list(MotionType))
@pytest.mark.parametrize("side", [PRO, CON])
def test_v6b_differs_from_v6_only_in_rule_1(mtype, side):
    learner = CON if side == PRO else PRO
    s6, u6 = case_plan_v6.build_case_plan_prompt("M", side, learner, OpponentDifficulty.HARD, mtype, "R")
    sb, ub = case_plan_v6b.build_case_plan_prompt("M", side, learner, OpponentDifficulty.HARD, mtype, BP, BC)
    label = "Đề xuất" if side == PRO else "Phản đối"
    block = case_plan_v6b.BURDEN_RULE.format(motion="M", burden_pro=BP, burden_con=BC, ai_side_label=label,
                                            ai_burden=BP if side == PRO else BC)
    old_rule = case_plan_v6.FIXED_READING_RULE.format(motion_reading="R")
    assert sb == s6.replace(old_rule, block)  # MOI thu khac giu nguyen (ke ca 2 cau giu lai cua phe De xuat)
    assert ub == u6.replace(case_plan_v6._OUTPUT_EXAMPLE_V6["motion_reading"],
                            case_plan_v6b._OUTPUT_EXAMPLE_V6B["motion_reading"])
    with pytest.raises(ValueError):
        case_plan_v6b.build_case_plan_prompt("M", side, learner, OpponentDifficulty.HARD, mtype, BP, None)


# ---------------- motions_v3 + batch ----------------


def test_motions_v3_mirrors_v2_and_is_not_ready():
    v2 = json.loads(MOTIONS_V2.read_text(encoding="utf-8"))["motions"]
    v3 = json.loads(MOTIONS_V3.read_text(encoding="utf-8"))["motions"]
    assert [(m["id"], m["text"], m["motion_type"]) for m in v3] == [(m["id"], m["text"], m["motion_type"]) for m in v2]
    assert all("motion_reading" not in m and m["burden_pro"] and m["burden_con"] for m in v3)
    motions = load_motions(MOTIONS_V3)
    assert motions[0]["burden_pro"] == v3[0]["burden_pro"] and motions[0]["motion_reading"] is None
    # chua duyet (draft) hoac con gia tri giu cho -> batch tu choi
    assert draft_motions(motions) == [m["id"] for m in v3 if m["reading_status"] == "draft" or "[CHỜ" in
                                      m["burden_pro"] + m["burden_con"]]
    approved_placeholder = [{**motions[0], "reading_status": "approved", "burden_pro": "[CHỜ KHOA GỬI]"}]
    assert draft_motions(approved_placeholder) == ["P1"]


@pytest.mark.parametrize("version,sent", [("case_plan_v5", False), ("case_plan_v6b", True)])
async def test_batch_sends_burdens_only_for_v6b(tmp_path, version, sent):
    motions = [{**load_motions(MOTIONS_V3)[8], "burden_pro": BP, "burden_con": BC, "reading_status": "approved"}]  # V1
    runs = build_runs(motions)[:1]  # V1 pro, do kho easy
    fake = FakeLLMClient([EASY_CASE])
    [record] = await run_batch(runs, fake, None, Settings(_env_file=None, case_plan_prompt_version=version),
                               tmp_path / "b.jsonl")
    assert (record["motion_type"], record["burden_pro"], record["burden_con"]) == ("value", BP, BC)
    assert record["burdens_sent"] is sent and record["motion_reading_sent"] is None
    assert (BP in fake.calls[0]["system"]) is sent and record["prompt_version"] == version
    if sent:
        assert record["case_file"]["motion_reading"] == BP


async def test_batch_main_refuses_placeholder_burdens(monkeypatch, capsys, tmp_path):
    from scripts import run_case_plan_batch as rb

    raw = json.loads(MOTIONS_V3.read_text(encoding="utf-8"))
    for m in raw["motions"]:
        m["reading_status"] = "approved"
    raw["motions"][5]["burden_con"] = "[CHỜ KHOA GỬI]"  # duyet nhung VAN con gia tri giu cho (file tam)
    path = tmp_path / "m3.json"
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["run_case_plan_batch", "--motions", str(path), "--prompt-version", "v6b",
                                     "--out-dir", str(tmp_path / "out")])
    monkeypatch.setattr(rb, "get_llm_client", lambda *a, **k: pytest.fail("khong duoc tao LLM client"))
    assert await rb.main() == 2
    assert "gia tri giu cho (C2)" in capsys.readouterr().out


def _rec(run_index, status, **extra):
    return {"run_index": run_index, "motion_id": "V1", "motion": "M", "ai_side": "pro", "learner_side": "con",
            "difficulty": "easy", "final_status": status, "motion_type": "value", "burden_pro": BP, "burden_con": BC,
            **extra}


def test_only_failed_reruns_infra_failures_by_default():
    records = [_rec(0, "ready"), _rec(1, "llm_error"), _rec(2, "budget_exceeded"), _rec(3, "invalid_output")]
    assert [r["run_index"] for r in runs_from_failed(records)] == [1, 2]
    with_content = runs_from_failed(records, include_content_failures=True)
    assert [r["run_index"] for r in with_content] == [1, 2, 3]
    assert with_content[0]["burden_pro"] == BP and with_content[0]["motion_type"] == "value"


async def test_only_failed_main_message_when_nothing_to_rerun(monkeypatch, capsys, tmp_path):
    from scripts import run_case_plan_batch as rb

    old = tmp_path / "old_case_plan_v5.jsonl"
    old.write_text("\n".join(json.dumps(_rec(i, s, prompt_version="case_plan_v5"))
                             for i, s in enumerate(["ready", "invalid_output"])), encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["run_case_plan_batch", "--only-failed", str(old)])
    monkeypatch.setattr(rb, "get_llm_client", lambda *a, **k: pytest.fail("khong duoc tao LLM client"))
    assert await rb.main() == 0
    assert "khong co lan chay loi ha tang nao" in capsys.readouterr().out


# ---------------- so sanh ----------------


def _cmp(run_index, status, version, rerun_of=None, side="pro"):
    return {"run_index": run_index, "motion_id": "V1", "motion": f"M{run_index}", "ai_side": side, "difficulty": "easy",
            "motion_type": "value", "prompt_version": version, "final_status": status, "total_latency_ms": 10,
            "final_vague_evidence": None, "rerun_of": rerun_of, "final_reviewer_verdict": "pass",
            "case_file": {"x": 1} if status == "ready" else None,
            "attempts": [{"attempt": 1, "purpose": "case_plan", "success": status == "ready", "failure_kind": None,
                          "reviewer_verdict": "pass", "schema_rejected": False, "tokens_in": 10,
                          "rate_limit_wait_ms": None, "retry_feedback": None, "reviewer_detail": {}}]}


def _write(path, records):
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records), encoding="utf-8")
    return path


def test_rerun_replaces_any_failed_status(tmp_path):
    orig = _write(tmp_path / "x_case_plan_v6b.jsonl", [
        _cmp(0, "ready", "case_plan_v6b"), _cmp(1, "budget_exceeded", "case_plan_v6b"),
        _cmp(2, "invalid_output", "case_plan_v6b")])
    rerun = _write(tmp_path / "x_case_plan_v6b_rerun.jsonl", [
        _cmp(1, "ready", "case_plan_v6b", rerun_of="x_case_plan_v6b.jsonl"),
        _cmp(2, "ready", "case_plan_v6b", rerun_of="x_case_plan_v6b.jsonl")])
    records, replaced = load_group([orig, rerun])
    assert replaced == 2 and sorted(r["final_status"] for r in records) == ["ready"] * 3


def test_compare_v5_old_file_vs_v6b_and_exact_version_warning(tmp_path):
    v5 = _write(tmp_path / "a_case_plan_v5.jsonl", [_cmp(0, "ready", "case_plan_v5"), _cmp(1, "ready", "case_plan_v5")])
    v6b = _write(tmp_path / "b_case_plan_v6b.jsonl", [_cmp(0, "ready", "case_plan_v6b"),
                                                      _cmp(1, "invalid_output", "case_plan_v6b")])
    text = compare({"v5": [v5], "v6b": [v6b]})
    assert "Cau hinh (motion, ai_side, difficulty) chung: 2" in text and "CANH BAO" not in text
    wrong = compare({"v5": [v5], "v6": [v6b]})  # file v6b dua nham vao nhom v6 -> phai canh bao
    assert "CANH BAO: nhom v6 chua file prompt_version khac (case_plan_v6b)" in wrong


# ---------------- gan nhan: ngu canh ----------------


def test_label_context_uses_burdens_for_motions_v3(tmp_path):
    raw = {"motions": [{"id": "V1", "text": "M", "motion_type": "value", "burden_pro": BP, "burden_con": BC},
                       {"id": "P1", "text": "N", "motion_type": "policy", "motion_reading": "R chuan"}]}
    path = tmp_path / "m.json"
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    ctx = lcs.load_canonical_readings(path)
    assert ctx == {"V1": f"De xuat phai chung minh: {BP} | Phan doi phai chung minh: {BC}", "P1": "R chuan"}
