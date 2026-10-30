"""
Thi nghiem v7 (dev log muc 2.16): case_plan_v7 = v5 + khoi ganh nang chung minh; API burden khong can motion_type;
batch --prompt-version v7 + --repeat N; so sanh: chi so chinh "so luot co side_flip" + danh sach xac nhan. LLM gia.
"""
import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.main import app
from app.opponent.models import DebateSide, LLMCallPurpose, OpponentCaseFile, OpponentDifficulty, OpponentLLMCall, OpponentSession
from app.opponent.prompts import case_plan_v5, case_plan_v7
from app.opponent.service import generate_case_file
from scripts.compare_case_plan_batches import compare, flagged_runs
from scripts.run_case_plan_batch import build_runs, load_motions, run_batch
from tests.conftest import VALID_CASE_FILE, FakeLLMClient, make_case_file

ROOT = Path(__file__).resolve().parent.parent
MOTIONS_V3 = ROOT / "experiments" / "motions_v3.json"
BP = "Tác hại của mạng xã hội đối với người từ 15 đến 24 tuổi lớn hơn lợi ích của nó."
BC = "Lợi ích của mạng xã hội đối với người từ 15 đến 24 tuổi lớn hơn hoặc ít nhất ngang bằng tác hại của nó."
V7 = Settings(_env_file=None, case_plan_prompt_version="case_plan_v7")
PRO, CON = DebateSide.PRO, DebateSide.CON
EASY_CASE = json.dumps(make_case_file(2))


def _payload(**overrides) -> dict:
    return {"external_session_id": f"main-{uuid.uuid4()}", "motion": "Mạng xã hội gây hại nhiều hơn có lợi cho giới trẻ",
            "learner_side": "pro", "ai_side": "con", "difficulty": "medium"} | overrides


# ---------------- prompt ----------------


@pytest.mark.parametrize("side", [PRO, CON])
@pytest.mark.parametrize("difficulty", list(OpponentDifficulty))
def test_v7_is_v5_verbatim_plus_burden_block_after_motion_line(side, difficulty):
    learner = CON if side == PRO else PRO
    s5, u5 = case_plan_v5.build_case_plan_prompt("Kiến nghị X", side, learner, difficulty)
    s7, u7 = case_plan_v7.build_case_plan_prompt("Kiến nghị X", side, learner, difficulty, BP, BC)
    assert s7 == s5  # system prompt NGUYEN VAN v5 (ke ca SIDE_RULE)
    label = "Đề xuất" if side == PRO else "Phản đối"
    block = (f"Phe Đề xuất phải chứng minh: {BP}\nPhe Phản đối phải chứng minh: {BC}\n"
             f"BẠN là phe {label}. Mọi luận điểm và phần cân nhắc của bạn phải chứng minh: {BP if side == PRO else BC}")
    assert u7 == u5.replace("KIẾN NGHỊ: Kiến nghị X\n", "KIẾN NGHỊ: Kiến nghị X\n" + block + "\n", 1)
    assert "Đây là kiến nghị" not in s7 + u7  # KHONG module motion_type
    with pytest.raises(ValueError):
        case_plan_v7.build_case_plan_prompt("X", side, learner, difficulty, BP, None)


# ---------------- API + service ----------------


async def test_burdens_without_motion_type_accepted_and_v7_used(client, db_session, fake_llm):
    app.dependency_overrides[get_settings] = lambda: V7
    model_case = {**VALID_CASE_FILE, "motion_reading": "Cách hiểu model tự viết."}
    fake_llm.responses = [json.dumps(model_case, ensure_ascii=False)]
    resp = await client.post("/opponent/sessions", json=_payload(burden_pro=BP, burden_con=BC))
    assert resp.status_code == 201, resp.text
    sid = uuid.UUID(resp.json()["opponent_session_id"])
    row = await db_session.get(OpponentSession, sid)
    assert (row.motion_type, row.burden_pro, row.burden_con) == (None, BP, BC)
    assert f"BẠN là phe Phản đối. Mọi luận điểm và phần cân nhắc của bạn phải chứng minh: {BC}" in fake_llm.calls[0]["user"]
    case = await db_session.scalar(select(OpponentCaseFile).where(OpponentCaseFile.session_id == sid))
    assert case.prompt_version == "case_plan_v7"
    assert case.content["motion_reading"] == "Cách hiểu model tự viết."  # KHONG ghi de
    plan = await db_session.scalar(select(OpponentLLMCall).where(
        OpponentLLMCall.session_id == sid, OpponentLLMCall.purpose == LLMCallPurpose.CASE_PLAN))
    assert plan.key_repairs is None


@pytest.mark.parametrize("extra,ok", [
    ({"burden_pro": BP}, False),  # thieu burden_con
    ({"burden_con": BC}, False),
    ({"motion_reading": "R"}, False),  # motion_reading van can motion_type (v6)
    ({"motion_type": "value", "burden_pro": BP, "burden_con": BC}, True),  # v6b van hop le
])
async def test_api_spec_rules_after_v7(client, fake_llm, extra, ok):
    fake_llm.responses = [json.dumps(VALID_CASE_FILE)]
    resp = await client.post("/opponent/sessions", json=_payload(**extra))
    assert resp.status_code == (201 if ok else 400), resp.text


async def test_v7_fallbacks_and_v6b_without_type_falls_back():
    fake = FakeLLMClient([EASY_CASE])
    out = await generate_case_file("M", PRO, CON, OpponentDifficulty.EASY, fake, V7)  # khong burden
    assert out.prompt_version == "case_plan_v5"
    fake = FakeLLMClient([EASY_CASE])
    out = await generate_case_file("M", PRO, CON, OpponentDifficulty.EASY, fake,
                                   Settings(_env_file=None, case_plan_prompt_version="case_plan_v6b"),
                                   burden_pro=BP, burden_con=BC)  # v6b can motion_type
    assert out.prompt_version == "case_plan_v5" and BP not in fake.calls[0]["system"] + fake.calls[0]["user"]
    out = await generate_case_file("M", PRO, CON, OpponentDifficulty.EASY, FakeLLMClient([EASY_CASE]), V7,
                                   burden_pro=BP, burden_con=BC)
    assert out.prompt_version == "case_plan_v7"
    assert out.case_file.motion_reading == make_case_file(2)["motion_reading"]


# ---------------- batch ----------------


def test_build_runs_repeat_rounds():
    motions = load_motions(MOTIONS_V3)
    runs = build_runs(motions, repeat=3)
    assert len(runs) == 72 and [r["run_index"] for r in runs] == list(range(72))
    assert [r["repeat_round"] for r in runs[::24]] == [1, 2, 3]
    one = build_runs(motions)
    for k in range(3):  # moi vong CUNG cau hinh (motion, phe, do kho)
        assert [(r["motion_id"], r["ai_side"], r["difficulty"]) for r in runs[24 * k:24 * (k + 1)]] == \
               [(r["motion_id"], r["ai_side"], r["difficulty"]) for r in one]
    assert {r["repeat_round"] for r in one} == {1}


async def test_batch_v7_sends_only_burdens_and_records_round(tmp_path):
    motions = [{**load_motions(MOTIONS_V3)[8], "burden_pro": BP, "burden_con": BC, "reading_status": "approved"}]
    runs = build_runs(motions, repeat=2)  # V1 pro easy, V1 con medium x 2 vong
    fake = FakeLLMClient([EASY_CASE, json.dumps(VALID_CASE_FILE)] * 2)
    records = await run_batch(runs, fake, None, V7, tmp_path / "b.jsonl")
    assert [(r["repeat_round"], r["run_index"], r["final_status"]) for r in records] == [
        (1, 0, "ready"), (1, 1, "ready"), (2, 2, "ready"), (2, 3, "ready")]
    assert all(r["burdens_sent"] and r["prompt_version"] == "case_plan_v7" for r in records)
    assert BP in fake.calls[0]["user"] and "Đây là kiến nghị" not in fake.calls[0]["system"]  # khong module
    lines = [json.loads(x) for x in (tmp_path / "b.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [x["repeat_round"] for x in lines] == [1, 1, 2, 2]


async def test_batch_main_validates_repeat_and_v7_burdens(monkeypatch, capsys, tmp_path):
    from scripts import run_case_plan_batch as rb

    raw = json.loads(MOTIONS_V3.read_text(encoding="utf-8"))
    for m in raw["motions"]:
        m["reading_status"] = "approved"
    good = tmp_path / "m3.json"
    good.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    raw["motions"][2]["burden_con"] = ""
    bad = tmp_path / "m3_bad.json"
    bad.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(rb, "get_llm_client", lambda *a, **k: pytest.fail("khong duoc tao LLM client"))

    monkeypatch.setattr("sys.argv", ["x", "--motions", str(good), "--prompt-version", "v7", "--repeat", "0"])
    assert await rb.main() == 2 and "--repeat phai >= 1" in capsys.readouterr().out
    monkeypatch.setattr("sys.argv", ["x", "--motions", str(bad), "--prompt-version", "v7"])
    assert await rb.main() == 2 and "case_plan_v7 can burden_pro + burden_con cho moi motion; thieu: P3" in capsys.readouterr().out


# ---------------- so sanh ----------------


def _rec(run_index, motion, side, version, flagged=(), status="ready", repeat_round=1, verdict="pass"):
    attempts = [{"attempt": n, "purpose": "case_plan", "success": False, "failure_kind": "side_flip",
                 "reviewer_verdict": "side_flip", "schema_rejected": False, "tokens_in": 10,
                 "rate_limit_wait_ms": None, "retry_feedback": None, "reviewer_detail": {"retry": "side_flip_neutral_retry"}}
                for n in flagged]
    attempts.append({"attempt": len(flagged) + 1, "purpose": "case_plan", "success": status == "ready",
                     "failure_kind": None, "reviewer_verdict": verdict, "schema_rejected": False, "tokens_in": 10,
                     "rate_limit_wait_ms": None, "retry_feedback": None, "reviewer_detail": {}})
    return {"run_index": run_index, "repeat_round": repeat_round, "motion_id": motion, "motion": motion,
            "ai_side": side, "difficulty": "easy", "motion_type": "value", "prompt_version": version,
            "final_status": status, "total_latency_ms": 10, "final_vague_evidence": None, "rerun_of": None,
            "final_reviewer_verdict": verdict if status == "ready" else None,
            "case_file": {"x": 1} if status == "ready" else None, "attempts": attempts}


def _write(path, records):
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records), encoding="utf-8")
    return path


def test_flagged_runs_main_metric_over_many_files_and_rounds(tmp_path):
    v5a = _write(tmp_path / "a_case_plan_v5.jsonl", [_rec(0, "V3", "con", "case_plan_v5", flagged=[1]),
                                                     _rec(1, "V4", "con", "case_plan_v5")])
    v5b = _write(tmp_path / "b_case_plan_v5.jsonl", [_rec(0, "V3", "con", "case_plan_v5"),
                                                     _rec(1, "V4", "con", "case_plan_v5", flagged=[1, 3],
                                                          status="invalid_output")])
    v7 = _write(tmp_path / "c_case_plan_v7_x2.jsonl", [
        _rec(0, "V3", "con", "case_plan_v7", repeat_round=1), _rec(1, "V4", "con", "case_plan_v7", repeat_round=1),
        _rec(2, "V3", "con", "case_plan_v7", repeat_round=2, flagged=[1]), _rec(3, "V4", "con", "case_plan_v7", repeat_round=2)])

    text = compare({"v5": [v5a, v5b], "v7": [v7]})
    head = text.split("Cau hinh (motion")[0]
    assert "CHI SO CHINH — so luot co side_flip" in head
    assert "  v5: 2/4 luot" in head and "  v7: 1/4 luot" in head
    assert "- V4 con easy | vong 1 | lan thu [1, 3] | invalid_output | b_case_plan_v5.jsonl:1" in head
    assert "- V3 con easy | vong 2 | lan thu [1] | ready | c_case_plan_v7_x2.jsonl:2" in head
    assert "Case file cuoi KHONG duoc reviewer cham pass" in text
    assert [x["repeat_round"] for x in flagged_runs([_rec(5, "M", "pro", "v", flagged=[2], repeat_round=3)])] == [3]
