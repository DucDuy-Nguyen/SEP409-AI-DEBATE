"""
POST /opponent/sessions/{external_session_id}/hints — DB that (Postgres test), LLM gia. Spec WF-02 muc 8.
Bai noi cong khai dua thang vao opponent_speeches (khong qua /turns): hint chi doc bang nay.
"""
import json
import uuid

import pytest
from sqlalchemy import select, update

from app.opponent.models import (
    LLMCallPurpose,
    OpponentHint,
    OpponentLLMCall,
    OpponentSession,
    OpponentSpeech,
    RoundType,
    SessionStatus,
    Speaker,
)
from tests.conftest import VALID_CASE_FILE
from tests.test_hint_unit import OUT, S

MOTION = "Nên cấm học sinh sử dụng điện thoại trong trường học"
CASE_MARKER = "MARKER_CASE_PLAN_7731"
ROUND = {1: RoundType.OPENING, 2: RoundType.OPENING, 3: RoundType.REBUTTAL, 4: RoundType.REBUTTAL,
         5: RoundType.CLOSING, 6: RoundType.CLOSING}
AI_TEXT = "Điện thoại làm học sinh mất tập trung trong giờ học. Cấm điện thoại giúp giảm bắt nạt trên mạng."


def _marked_case() -> dict:
    case = json.loads(json.dumps(VALID_CASE_FILE, ensure_ascii=False))
    case["weighing"] += f" {CASE_MARKER}"
    case["arguments"][0]["claim"] += f" {CASE_MARKER}"
    case["arguments"][0]["reasoning"] += f" {CASE_MARKER}"
    return case


async def _session(client, fake_llm, fake_reviewer, ai_side: str) -> str:
    """Session READY voi case file co chuoi danh dau. Reviewer gia tra position cua phe LEARNER (phan hint)."""
    external_id = f"hint-{uuid.uuid4()}"
    fake_llm.responses = [json.dumps(_marked_case(), ensure_ascii=False)]
    fake_reviewer.default_position = "ung_ho_kien_nghi" if ai_side == "pro" else "phan_doi_kien_nghi"
    resp = await client.post("/opponent/sessions", json={
        "external_session_id": external_id, "motion": MOTION, "ai_side": ai_side,
        "learner_side": "con" if ai_side == "pro" else "pro", "difficulty": "medium"})
    assert resp.status_code == 201 and resp.json()["status"] == "ready", resp.text
    # Tu day reviewer danh gia HINT -> phai dung phe learner.
    fake_reviewer.default_position = "phan_doi_kien_nghi" if ai_side == "pro" else "ung_ho_kien_nghi"
    fake_llm.calls.clear()
    fake_reviewer.calls.clear()
    return external_id


async def _sid(db_session, external_id):
    return await db_session.scalar(select(OpponentSession.id).where(OpponentSession.external_session_id == external_id))


async def _speak(db_session, external_id, ai_side: str, *turns: int):
    sid = await _sid(db_session, external_id)
    for t in turns:
        ai = (t % 2 == 1) == (ai_side == "pro") if t <= 4 else (t == 5) == (ai_side == "con")
        db_session.add(OpponentSpeech(session_id=sid, turn_index=t, round_type=ROUND[t],
                                      speaker=Speaker.AI if ai else Speaker.LEARNER,
                                      text=AI_TEXT if ai else f"Bài nói của learner lượt {t}."))
    await db_session.commit()


async def _hint(client, external_id, learner_turn, request_id="req-1", draft=None):
    body = {"request_id": request_id, "learner_turn_index": learner_turn}
    if draft is not None:
        body["learner_draft"] = draft
    return await client.post(f"/opponent/sessions/{external_id}/hints", json=body)


# ---------------- tao moi + idempotent ----------------


async def test_create_hint_201_then_idempotent_200(client, db_session, fake_llm, fake_reviewer):
    ext = await _session(client, fake_llm, fake_reviewer, "pro")  # learner con
    await _speak(db_session, ext, "pro", 1)
    fake_llm.responses = [OUT()]
    resp = await _hint(client, ext, 2, draft="Mình định nói về liên lạc khẩn cấp.")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert (body["learner_turn_index"], body["target_turn_index"], body["round_type"]) == (2, 1, "opening")
    assert len(body["strategies"]) == 2 and body["strategies"][0]["attack_type"] == "hidden_premise"
    assert body["prompt_version"] == "hint_v1" and body["llm_provider"] == "fake"
    assert len(fake_llm.calls) == 1 and AI_TEXT in fake_llm.calls[0]["user"]

    again = await _hint(client, ext, 2, draft="  Mình định nói về liên lạc khẩn cấp.  ")  # khac khoang trang -> cung input
    assert again.status_code == 200 and again.json() == body
    assert len(fake_llm.calls) == 1  # KHONG goi LLM lan 2

    sid = await _sid(db_session, ext)
    hint = await db_session.scalar(select(OpponentHint).where(OpponentHint.session_id == sid))
    assert hint.request_id == "req-1" and hint.learner_draft == "Mình định nói về liên lạc khẩn cấp."
    rows = (await db_session.scalars(select(OpponentLLMCall).where(OpponentLLMCall.hint_id == hint.id))).all()
    assert sorted(r.purpose.value for r in rows) == ["hint", "stance_review"]


@pytest.mark.parametrize("first_draft,second", [
    (None, {"learner_turn": 4}),
    (None, {"learner_turn": 2, "draft": "Bản nháp khác"}),
    ("Bản nháp đầu", {"learner_turn": 2}),  # co nhap -> khong nhap
])
async def test_same_request_id_different_input_409(client, db_session, fake_llm, fake_reviewer, first_draft, second):
    ext = await _session(client, fake_llm, fake_reviewer, "pro")
    await _speak(db_session, ext, "pro", 1, 2, 3)
    fake_llm.responses = [OUT()]
    assert (await _hint(client, ext, 2, draft=first_draft)).status_code == 201
    resp = await _hint(client, ext, second["learner_turn"], draft=second.get("draft"))
    assert resp.status_code == 409 and "request_id" in resp.json()["detail"]
    assert len(fake_llm.calls) == 1


# ---------------- KHONG doc case plan (spec muc 4) ----------------


async def test_no_prompt_ever_contains_case_file(client, db_session, fake_llm, fake_reviewer):
    ext = await _session(client, fake_llm, fake_reviewer, "con")  # learner pro
    sid = await _sid(db_session, ext)
    case_text = json.dumps(_marked_case(), ensure_ascii=False)
    assert CASE_MARKER in case_text
    await _speak(db_session, ext, "con", 1, 2, 3, 4, 5)
    fake_llm.responses = [OUT(), OUT()]
    assert (await _hint(client, ext, 3, "a")).status_code == 201
    assert (await _hint(client, ext, 6, "b")).status_code == 201
    prompts = [c["system"] + c["user"] for c in fake_llm.calls + fake_reviewer.calls]
    assert prompts and all(CASE_MARKER not in p for p in prompts)
    rows = (await db_session.scalars(select(OpponentLLMCall).where(
        OpponentLLMCall.session_id == sid, OpponentLLMCall.hint_id.is_not(None)))).all()
    assert rows and all(CASE_MARKER not in r.system_prompt + r.user_prompt for r in rows)
    # luot 6 (closing): target = luot 5, cac luot truoc co mat dang rut gon
    assert "lượt 5, nguyên văn" in fake_llm.calls[1]["user"] and "Lượt 1 – Học sinh" in fake_llm.calls[1]["user"]


# ---------------- loi ----------------


async def test_session_not_found_404(client):
    resp = await _hint(client, "khong-ton-tai", 2)
    assert resp.status_code == 404


async def test_session_not_ready_409(client, db_session, fake_llm, fake_reviewer):
    ext = await _session(client, fake_llm, fake_reviewer, "pro")
    sid = await _sid(db_session, ext)
    await db_session.execute(update(OpponentSession).where(OpponentSession.id == sid)
                             .values(status=SessionStatus.PLANNING))
    await db_session.commit()
    resp = await _hint(client, ext, 2)
    assert resp.status_code == 409 and "chua san sang" in resp.json()["detail"]


async def test_target_not_generated_409(client, db_session, fake_llm, fake_reviewer):
    ext = await _session(client, fake_llm, fake_reviewer, "pro")
    resp = await _hint(client, ext, 2)  # luot 1 cua AI chua co
    assert resp.status_code == 409 and "chua duoc sinh" in resp.json()["detail"]
    assert fake_llm.calls == []


@pytest.mark.parametrize("ai_side,learner_turn", [("con", 1), ("con", 2), ("pro", 3), ("pro", 6)])
async def test_invalid_learner_turn_400(client, db_session, fake_llm, fake_reviewer, ai_side, learner_turn):
    ext = await _session(client, fake_llm, fake_reviewer, ai_side)
    await _speak(db_session, ext, ai_side, 1, 2)
    resp = await _hint(client, ext, learner_turn)
    assert resp.status_code == 400, resp.text
    assert fake_llm.calls == []


@pytest.mark.parametrize("body", [
    {"request_id": "", "learner_turn_index": 2},
    {"request_id": "   ", "learner_turn_index": 2},
    {"request_id": "r", "learner_turn_index": 2, "learner_draft": "x" * 5001},
    {"request_id": "r" * 201, "learner_turn_index": 2},
    {"request_id": "r", "learner_turn_index": 0},
    {"request_id": "r", "learner_turn_index": 7},
    {"learner_turn_index": 2},
])
async def test_schema_422(client, body):
    resp = await client.post("/opponent/sessions/any/hints", json=body)
    assert resp.status_code == 422


async def test_llm_broken_json_502_and_logged(client, db_session, fake_llm, fake_reviewer):
    ext = await _session(client, fake_llm, fake_reviewer, "pro")
    await _speak(db_session, ext, "pro", 1)
    fake_llm.responses = ["hong"] * 3
    resp = await _hint(client, ext, 2)
    assert resp.status_code == 502
    sid = await _sid(db_session, ext)
    assert await db_session.scalar(select(OpponentHint).where(OpponentHint.session_id == sid)) is None
    rows = (await db_session.scalars(select(OpponentLLMCall).where(
        OpponentLLMCall.session_id == sid, OpponentLLMCall.purpose == LLMCallPurpose.HINT))).all()
    assert [r.failure_kind for r in rows] == ["invalid_json"] * 3 and all(r.hint_id is None for r in rows)
    # loi khong luu hint -> goi lai cung request_id duoc sinh moi
    fake_llm.responses = [OUT()]
    assert (await _hint(client, ext, 2)).status_code == 201


async def test_side_flip_every_attempt_502(client, db_session, fake_llm, fake_reviewer):
    ext = await _session(client, fake_llm, fake_reviewer, "pro")  # learner con
    await _speak(db_session, ext, "pro", 1)
    fake_reviewer.default_position = "ung_ho_kien_nghi"  # bênh phe AI
    fake_llm.responses = [OUT()] * 3
    resp = await _hint(client, ext, 2)
    assert resp.status_code == 502 and "side_flip" in resp.json()["detail"]


async def test_openapi_declares_hint_errors(client):
    spec = (await client.get("/openapi.json")).json()
    responses = spec["paths"]["/opponent/sessions/{external_session_id}/hints"]["post"]["responses"]
    assert {"200", "201", "400", "404", "409", "422", "502", "503"} <= set(responses)


async def test_strategy_with_null_evidence_roundtrip(client, db_session, fake_llm, fake_reviewer):
    ext = await _session(client, fake_llm, fake_reviewer, "pro")
    await _speak(db_session, ext, "pro", 1)
    fake_llm.responses = [OUT(S(evidence=None), S(claim="Cấm giúp giảm bắt nạt", attack="turn_the_argument"))]
    body = (await _hint(client, ext, 2)).json()
    assert body["strategies"][0]["evidence_to_look_for"] is None
    assert body["strategies"][1]["attack_type"] == "turn_the_argument"


async def test_direction_too_long_every_attempt_502(client, db_session, fake_llm, fake_reviewer):
    ext = await _session(client, fake_llm, fake_reviewer, "pro")
    await _speak(db_session, ext, "pro", 1)
    long = " ".join(["từ"] * 61)
    fake_llm.responses = [OUT(S(), S(attack="counterexample", direction=long))] * 3
    resp = await _hint(client, ext, 2)
    assert resp.status_code == 502
    sid = await _sid(db_session, ext)
    rows = (await db_session.scalars(select(OpponentLLMCall).where(
        OpponentLLMCall.session_id == sid, OpponentLLMCall.purpose == LLMCallPurpose.HINT))).all()
    assert [r.failure_kind for r in rows] == ["direction_too_long"] * 3


async def test_llm_not_configured_503(client, db_session, fake_llm, fake_reviewer):
    from app.main import app
    from app.opponent import service
    from app.opponent.router import get_llm_client_factory

    ext = await _session(client, fake_llm, fake_reviewer, "pro")
    await _speak(db_session, ext, "pro", 1)

    def broken():
        raise service.LLMNotConfiguredError("GROQ_API_KEY chua duoc set")

    app.dependency_overrides[get_llm_client_factory] = lambda: broken
    resp = await _hint(client, ext, 2)
    assert resp.status_code == 503
    sid = await _sid(db_session, ext)
    assert await db_session.scalar(select(OpponentHint).where(OpponentHint.session_id == sid)) is None


@pytest.mark.parametrize("same_input", [True, False])
async def test_concurrent_same_request_id_integrity_branch(client, db_session, fake_llm, fake_reviewer, monkeypatch,
                                                         same_input):
    """Gia lap request khac luu CUNG request_id trong luc LLM dang chay -> nhanh IntegrityError."""
    from app.opponent import hint_service

    ext = await _session(client, fake_llm, fake_reviewer, "pro")
    await _speak(db_session, ext, "pro", 1, 2, 3)
    sid = await _sid(db_session, ext)
    real_run = hint_service.run_hint

    async def run_then_competitor_saves(context, *args, **kwargs):
        result = await real_run(context, *args, **kwargs)
        db_session.add(OpponentHint(
            session_id=sid, request_id="req-1", learner_turn_index=2 if same_input else 4, target_turn_index=1,
            learner_draft=None, strategies=[S(), S(attack="counterexample")], prompt_version="hint_v1",
            llm_provider="fake", llm_model="other", temperature=0.2, latency_ms=1))
        await db_session.commit()
        return result

    monkeypatch.setattr(hint_service, "run_hint", run_then_competitor_saves)
    fake_llm.responses = [OUT()]
    resp = await _hint(client, ext, 2)
    if same_input:
        assert resp.status_code == 200 and resp.json()["llm_model"] == "other"  # ban cua request kia
    else:
        assert resp.status_code == 409
    rows = (await db_session.scalars(select(OpponentLLMCall).where(
        OpponentLLMCall.session_id == sid, OpponentLLMCall.purpose == LLMCallPurpose.HINT))).all()
    assert len(rows) == 1 and rows[0].hint_id is None  # log van giu, khong gan vao hint cua request kia

