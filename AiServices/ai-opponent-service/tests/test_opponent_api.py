"""
Test API + DB that (Postgres ai_generation_test), LLM gia lap bang FakeLLMClient.
"""
import asyncio
import json
import uuid

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings, get_settings
from app.main import app
from app.opponent.models import (
    DebateSide,
    LLMCallPurpose,
    OpponentCaseFile,
    OpponentDifficulty,
    OpponentLLMCall,
    OpponentSession,
    ReviewerVerdict,
    SessionStatus,
)
from app.opponent.router import get_llm_client_factory, get_stance_reviewer_factory
from tests.conftest import TEST_SETTINGS, VALID_CASE_FILE, make_case_file

MOTION = "Học sinh không nên có bài tập về nhà"


def _payload(**overrides) -> dict:
    return {
        "external_session_id": f"main-{uuid.uuid4()}",
        "motion": MOTION,
        "learner_side": "pro",
        "ai_side": "con",
        "difficulty": "medium",
        "language": "vi",
    } | overrides


async def _count(db, model, session_id) -> int:
    return await db.scalar(select(func.count()).select_from(model).where(model.session_id == session_id))


async def _llm_calls(db, session_id, purpose: LLMCallPurpose | None = LLMCallPurpose.CASE_PLAN) -> list[OpponentLLMCall]:
    """Mac dinh chi lay loi goi planner (case_plan); purpose=None -> moi loi goi (ke ca stance_review)."""
    query = select(OpponentLLMCall).where(OpponentLLMCall.session_id == session_id)
    if purpose is not None:
        query = query.where(OpponentLLMCall.purpose == purpose)
    return list((await db.scalars(query.order_by(OpponentLLMCall.attempt))).all())


async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_create_session_runs_case_planning(client, db_session, fake_llm):
    fake_llm.responses = [json.dumps(VALID_CASE_FILE, ensure_ascii=False)]
    payload = _payload(motion=f"  {MOTION}  ")

    resp = await client.post("/opponent/sessions", json=payload)

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert set(body) == {"opponent_session_id", "status"}  # KHONG tra case file
    assert body["status"] == "ready"

    sid = uuid.UUID(body["opponent_session_id"])
    row = await db_session.get(OpponentSession, sid)
    assert row.external_session_id == payload["external_session_id"]
    assert row.motion == MOTION  # da strip
    assert (row.ai_side, row.learner_side) == (DebateSide.CON, DebateSide.PRO)

    case_file = await db_session.scalar(select(OpponentCaseFile).where(OpponentCaseFile.session_id == sid))
    assert case_file.content == VALID_CASE_FILE  # JSONB round-trip
    assert case_file.prompt_version == "case_plan_v5"
    calls = await _llm_calls(db_session, sid)
    assert len(calls) == 1 and calls[0].success and calls[0].purpose.value == "case_plan"
    assert "Bạn thuộc phe Phản đối. Người học thuộc phe Đề xuất." in calls[0].system_prompt
    assert calls[0].vague_evidence == []  # case file sach -> da quet, khong co cum nao


async def test_same_side_returns_400_without_calling_llm(client, fake_llm):
    resp = await client.post("/opponent/sessions", json=_payload(learner_side="pro", ai_side="pro"))

    assert resp.status_code == 400
    assert fake_llm.calls == []


async def test_create_session_validation_returns_422(client):
    assert (await client.post("/opponent/sessions", json=_payload(motion="   "))).status_code == 422
    assert (await client.post("/opponent/sessions", json=_payload(external_session_id=" "))).status_code == 422
    assert (await client.post("/opponent/sessions", json=_payload(ai_side="neutral"))).status_code == 422
    assert (await client.post("/opponent/sessions", json=_payload(language="en"))).status_code == 422
    missing = _payload()
    del missing["learner_side"]
    assert (await client.post("/opponent/sessions", json=missing)).status_code == 422


async def test_idempotent_same_external_id_calls_llm_once(client, fake_llm):
    fake_llm.responses = [json.dumps(VALID_CASE_FILE)]
    payload = _payload()

    first = await client.post("/opponent/sessions", json=payload)
    # Trung khop du lieu (motion co khoang trang thua van coi la trung vi da strip)
    second = await client.post("/opponent/sessions", json=payload | {"motion": f" {MOTION} "})

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json() == first.json()
    assert len(fake_llm.calls) == 1


@pytest.mark.parametrize(
    "changes,expected_fields",
    [
        ({"motion": "Mot motion khac"}, ["motion"]),
        ({"learner_side": "con", "ai_side": "pro"}, ["learner_side", "ai_side"]),
        ({"difficulty": "hard"}, ["difficulty"]),
        ({"motion": "Khac", "difficulty": "easy"}, ["motion", "difficulty"]),
    ],
)
async def test_same_external_id_with_different_data_returns_409(client, db_session, fake_llm, changes, expected_fields):
    fake_llm.responses = [json.dumps(VALID_CASE_FILE)]
    payload = _payload()
    first = await client.post("/opponent/sessions", json=payload)
    assert first.status_code == 201

    resp = await client.post("/opponent/sessions", json=payload | changes)

    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert payload["external_session_id"] in detail
    for f in ["motion", "learner_side", "ai_side", "difficulty"]:
        assert (f in detail) == (f in expected_fields), (f, detail)
    assert len(fake_llm.calls) == 1
    sid = uuid.UUID(first.json()["opponent_session_id"])
    assert (await db_session.get(OpponentSession, sid)).motion == MOTION  # phien cu khong doi


async def test_failed_session_with_different_data_returns_409_without_replanning(client, fake_llm):
    payload = _payload()
    fake_llm.responses = [RuntimeError("loi mang")]
    assert (await client.post("/opponent/sessions", json=payload)).status_code == 502

    resp = await client.post("/opponent/sessions", json=payload | {"difficulty": "easy"})

    assert resp.status_code == 409 and "difficulty" in resp.json()["detail"]
    assert len(fake_llm.calls) == 1


async def test_wrong_argument_count_retries_then_502(client, db_session, fake_llm):
    # medium can 3 luan diem; ca 3 lan LLM (CASE_PLAN_MAX_ATTEMPTS mac dinh) deu tra 2 -> het luot thu -> 502
    fake_llm.responses = [json.dumps(make_case_file(2))] * 3
    payload = _payload(difficulty="medium")

    resp = await client.post("/opponent/sessions", json=payload)

    assert resp.status_code == 502
    assert len(fake_llm.calls) == 3
    assert "[PHẢN HỒI LẦN THỬ TRƯỚC]" in fake_llm.calls[1]["user"]
    session = (await client.get(f"/opponent/sessions/{payload['external_session_id']}")).json()
    assert session["status"] == "failed" and session["case_file"] is None
    calls = await _llm_calls(db_session, uuid.UUID(session["id"]))
    assert [c.success for c in calls] == [False, False, False]
    assert all("can dung 3 luan diem" in c.error for c in calls)


async def test_easy_accepts_exactly_two_arguments(client, fake_llm):
    fake_llm.responses = [json.dumps(make_case_file(2))]
    resp = await client.post("/opponent/sessions", json=_payload(difficulty="easy"))
    assert resp.status_code == 201 and resp.json()["status"] == "ready"


async def test_failed_session_is_replanned_on_next_call(client, db_session, fake_llm):
    payload = _payload()
    fake_llm.responses = [RuntimeError("Groq tra ve noi dung rong")]
    first = await client.post("/opponent/sessions", json=payload)
    assert first.status_code == 502
    assert "Groq tra ve noi dung rong" in first.json()["detail"]

    fake_llm.responses = [json.dumps(VALID_CASE_FILE)]
    second = await client.post("/opponent/sessions", json=payload)

    assert second.status_code == 200
    assert second.json()["status"] == "ready"
    sid = uuid.UUID(second.json()["opponent_session_id"])
    calls = await _llm_calls(db_session, sid)
    assert [c.success for c in calls] == [False, True]
    assert calls[0].raw_output is None and "RuntimeError" in calls[0].error


async def test_second_case_file_for_same_session_is_rejected(client, db_session, fake_llm):
    fake_llm.responses = [json.dumps(VALID_CASE_FILE)]
    body = (await client.post("/opponent/sessions", json=_payload())).json()
    sid = uuid.UUID(body["opponent_session_id"])

    # Tang DB: UNIQUE(session_id) chan case file thu 2.
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(
                OpponentCaseFile(
                    session_id=sid,
                    content=VALID_CASE_FILE,
                    prompt_version="case_plan_v3",
                    llm_provider="fake",
                    llm_model="fake-model",
                    temperature=0.7,
                )
            )
    assert await _count(db_session, OpponentCaseFile, sid) == 1


async def test_sides_check_constraint_in_db(db_session):
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(
                OpponentSession(
                    external_session_id="x",
                    motion=MOTION,
                    ai_side=DebateSide.PRO,
                    learner_side=DebateSide.PRO,
                    difficulty=OpponentDifficulty.EASY,
                )
            )


async def _insert_planning_session(db_session, external_id: str, age_seconds: int) -> None:
    """Tao phien PLANNING voi updated_at = now() - age_seconds."""
    db_session.add(
        OpponentSession(
            external_session_id=external_id,
            motion=MOTION,
            ai_side=DebateSide.CON,
            learner_side=DebateSide.PRO,
            difficulty=OpponentDifficulty.MEDIUM,
            status=SessionStatus.PLANNING,
        )
    )
    await db_session.flush()
    await db_session.execute(
        update(OpponentSession)
        .where(OpponentSession.external_session_id == external_id)
        .values(updated_at=func.now() - func.make_interval(0, 0, 0, 0, 0, 0, age_seconds))
    )


async def test_conflict_while_planning(client, db_session, fake_llm):
    payload = _payload()
    await _insert_planning_session(db_session, payload["external_session_id"], age_seconds=0)

    resp = await client.post("/opponent/sessions", json=payload)

    assert resp.status_code == 409
    assert fake_llm.calls == []


async def test_planning_just_under_stale_threshold_returns_409(client, db_session, fake_llm):
    threshold = TEST_SETTINGS.case_plan_stale_after_seconds
    payload = _payload()
    await _insert_planning_session(db_session, payload["external_session_id"], age_seconds=threshold - 30)

    resp = await client.post("/opponent/sessions", json=payload)

    assert resp.status_code == 409
    assert "dang chuan bi case" in resp.json()["detail"]
    assert fake_llm.calls == []


async def test_planning_past_stale_threshold_is_replanned(client, db_session, fake_llm):
    threshold = TEST_SETTINGS.case_plan_stale_after_seconds
    payload = _payload()
    await _insert_planning_session(db_session, payload["external_session_id"], age_seconds=threshold + 30)
    fake_llm.responses = [json.dumps(VALID_CASE_FILE)]

    resp = await client.post("/opponent/sessions", json=payload)

    assert resp.status_code == 200 and resp.json()["status"] == "ready"
    assert len(fake_llm.calls) == 1


async def test_get_routes_use_external_session_id(client, fake_llm):
    fake_llm.responses = [json.dumps(VALID_CASE_FILE)]
    payload = _payload()
    body = (await client.post("/opponent/sessions", json=payload)).json()
    ext = payload["external_session_id"]

    session = (await client.get(f"/opponent/sessions/{ext}")).json()
    assert session["id"] == body["opponent_session_id"]
    assert session["learner_side"] == "pro"
    assert session["case_file"]["content"] == VALID_CASE_FILE

    case_plan = await client.get(f"/opponent/sessions/{ext}/case-plan")
    assert case_plan.status_code == 200 and case_plan.json()["content"] == VALID_CASE_FILE

    # id noi bo KHONG dung duoc trong path
    assert (await client.get(f"/opponent/sessions/{body['opponent_session_id']}")).status_code == 404


async def test_get_unknown_session_returns_404(client):
    assert (await client.get("/opponent/sessions/khong-ton-tai")).status_code == 404
    assert (await client.get("/opponent/sessions/khong-ton-tai/case-plan")).status_code == 404


async def test_case_plan_post_route_removed(client):
    resp = await client.post("/opponent/sessions/abc/case-plan")
    assert resp.status_code == 405


async def test_missing_llm_key_returns_503_and_creates_nothing(client, db_session):
    app.dependency_overrides.pop(get_llm_client_factory)
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, llm_provider="groq", groq_api_key="")
    payload = _payload()

    resp = await client.post("/opponent/sessions", json=payload)

    assert resp.status_code == 503
    assert "GROQ_API_KEY" in resp.json()["detail"]
    assert (await client.get(f"/opponent/sessions/{payload['external_session_id']}")).status_code == 404


async def test_ready_session_does_not_need_llm_key(client, fake_llm):
    fake_llm.responses = [json.dumps(VALID_CASE_FILE)]
    payload = _payload()
    assert (await client.post("/opponent/sessions", json=payload)).status_code == 201

    app.dependency_overrides.pop(get_llm_client_factory)
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, llm_provider="groq", groq_api_key="")

    resp = await client.post("/opponent/sessions", json=payload)
    assert resp.status_code == 200 and resp.json()["status"] == "ready"


async def test_budget_exceeded_returns_504_and_marks_failed(client, db_session, fake_llm):
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, case_plan_total_budget_seconds=0.2)
    fake_llm.responses = [json.dumps(VALID_CASE_FILE)]
    fake_llm.delay_seconds = 1.0
    payload = _payload()

    resp = await client.post("/opponent/sessions", json=payload)

    assert resp.status_code == 504
    assert resp.json()["detail"].startswith("budget_exceeded")
    session = (await client.get(f"/opponent/sessions/{payload['external_session_id']}")).json()
    assert session["status"] == "failed" and session["case_file"] is None
    [call] = await _llm_calls(db_session, uuid.UUID(session["id"]))
    assert call.success is False and call.error.startswith("budget_exceeded")


async def test_case_file_integrity_error_returns_200_with_existing_session(client, db_session, fake_llm):
    """
    Gia lap race: trong luc request nay cho LLM, 1 request khac (vd chay lai phien bi coi la ket)
    da ghi case file + READY. Insert case file cua request nay dung UNIQUE(session_id).
    """
    payload = _payload()
    loop = asyncio.get_running_loop()
    other_content = make_case_file(3) | {"weighing": "Case file cua request kia"}

    async def other_request_wins():
        session = await db_session.scalar(
            select(OpponentSession).where(OpponentSession.external_session_id == payload["external_session_id"])
        )
        db_session.add(
            OpponentCaseFile(
                session_id=session.id,
                content=other_content,
                prompt_version="case_plan_v3",
                llm_provider="other",
                llm_model="other",
                temperature=0.7,
            )
        )
        session.status = SessionStatus.READY
        await db_session.commit()

    # FakeLLMClient.generate chay trong thread -> day coroutine ve event loop chinh va doi xong.
    fake_llm.before_return = lambda: asyncio.run_coroutine_threadsafe(other_request_wins(), loop).result()
    fake_llm.responses = [json.dumps(VALID_CASE_FILE)]

    resp = await client.post("/opponent/sessions", json=payload)

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "ready"
    session = (await client.get(f"/opponent/sessions/{payload['external_session_id']}")).json()
    assert resp.json()["opponent_session_id"] == session["id"]
    assert session["case_file"]["content"] == other_content  # giu case file co san
    sid = uuid.UUID(session["id"])
    assert await _count(db_session, OpponentCaseFile, sid) == 1
    [call] = await _llm_calls(db_session, sid)  # log LLM call cua request thua van duoc giu
    assert call.success is True


async def test_vague_evidence_is_stored_but_not_rejected(client, db_session, fake_llm):
    content = make_case_file(3)
    # Cum rong (chi log) — KHONG dung cum bi cam ("nghiên cứu cho thấy"...) vi cum do bi reject.
    content["arguments"][0]["reasoning"] = "Theo thống kê, 70% học sinh thiếu ngủ."
    fake_llm.responses = [json.dumps(content, ensure_ascii=False)]

    resp = await client.post("/opponent/sessions", json=_payload())

    assert resp.status_code == 201 and resp.json()["status"] == "ready"  # KHONG reject
    [call] = await _llm_calls(db_session, uuid.UUID(resp.json()["opponent_session_id"]))
    assert call.vague_evidence == [
        {"phrase": "thống kê / theo báo cáo", "field": "arguments[0].reasoning", "level": "low",
         "rule": "thong_ke", "match": "thống kê"},
        {"phrase": "%", "field": "arguments[0].reasoning", "level": "low", "rule": "phan_tram", "match": "70%"},
    ]


async def test_failed_attempts_have_null_vague_evidence(client, db_session, fake_llm):
    fake_llm.responses = ["khong phai json", json.dumps(VALID_CASE_FILE)]

    resp = await client.post("/opponent/sessions", json=_payload())

    calls = await _llm_calls(db_session, uuid.UUID(resp.json()["opponent_session_id"]))
    assert [c.vague_evidence for c in calls] == [None, []]


# ---------------- Stance Reviewer qua API (luu DB) ----------------


async def test_reviewer_result_is_stored_in_llm_calls(client, db_session, fake_llm, fake_reviewer):
    fake_llm.responses = [json.dumps(VALID_CASE_FILE)]

    resp = await client.post("/opponent/sessions", json=_payload())

    assert resp.status_code == 201
    sid = uuid.UUID(resp.json()["opponent_session_id"])
    plan, review = await _llm_calls(db_session, sid, purpose=None)
    assert plan.purpose == LLMCallPurpose.CASE_PLAN and plan.reviewer_verdict == ReviewerVerdict.PASS
    assert plan.reviewer_detail["expected_position"] == "phan_doi_kien_nghi"
    assert review.purpose == LLMCallPurpose.STANCE_REVIEW
    assert (review.llm_model, review.prompt_version, review.temperature) == ("fake-reviewer", "stance_review_v1", 0.0)
    assert review.raw_output and review.system_prompt != plan.system_prompt


async def test_side_flip_every_attempt_returns_502_and_failed(client, db_session, fake_llm, fake_reviewer):
    fake_llm.responses = [json.dumps(VALID_CASE_FILE)] * 3
    fake_reviewer.default_position = "ung_ho_kien_nghi"  # nguoc phe ai_side=con
    payload = _payload()

    resp = await client.post("/opponent/sessions", json=payload)

    assert resp.status_code == 502
    session = (await client.get(f"/opponent/sessions/{payload['external_session_id']}")).json()
    assert session["status"] == "failed" and session["case_file"] is None
    plans = await _llm_calls(db_session, uuid.UUID(session["id"]))
    assert [p.reviewer_verdict for p in plans] == [ReviewerVerdict.SIDE_FLIP] * 3


async def test_reviewer_disabled_skips_review(client, db_session, fake_llm):
    app.dependency_overrides.pop(get_stance_reviewer_factory)
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, stance_review_enabled=False)
    fake_llm.responses = [json.dumps(VALID_CASE_FILE)]

    resp = await client.post("/opponent/sessions", json=_payload())

    assert resp.status_code == 201
    calls = await _llm_calls(db_session, uuid.UUID(resp.json()["opponent_session_id"]), purpose=None)
    assert [c.purpose for c in calls] == [LLMCallPurpose.CASE_PLAN] and calls[0].reviewer_verdict is None


async def test_missing_reviewer_key_returns_503_and_creates_nothing(client, fake_llm):
    app.dependency_overrides.pop(get_stance_reviewer_factory)
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, stance_review_provider="groq", groq_api_key=""
    )
    payload = _payload()

    resp = await client.post("/opponent/sessions", json=payload)

    assert resp.status_code == 503 and "Stance reviewer" in resp.json()["detail"]
    assert fake_llm.calls == []
    assert (await client.get(f"/opponent/sessions/{payload['external_session_id']}")).status_code == 404


async def test_failure_kind_and_retry_feedback_are_stored(client, db_session, fake_llm):
    fake_llm.responses = [json.dumps(make_case_file(2)), json.dumps(VALID_CASE_FILE)]  # medium can 3

    resp = await client.post("/opponent/sessions", json=_payload(difficulty="medium"))

    assert resp.status_code == 201
    failed, ok = await _llm_calls(db_session, uuid.UUID(resp.json()["opponent_session_id"]))
    assert failed.failure_kind == "argument_count"
    assert failed.retry_feedback.startswith("[PHẢN HỒI LẦN THỬ TRƯỚC]")
    assert "cần ĐÚNG 3 luận điểm, bạn trả về 2" in failed.retry_feedback
    assert failed.retry_feedback in ok.user_prompt  # phan hoi da gui dung la phan hoi da log
    assert ok.failure_kind is None and ok.retry_feedback is None


async def test_tokens_and_rate_limit_wait_are_stored(client, db_session, fake_llm, monkeypatch):
    from app.opponent import service
    from tests.conftest import RateLimited

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(service, "_sleep", no_sleep)
    fake_llm.responses = [RateLimited("Please try again in 6.5s."), json.dumps(VALID_CASE_FILE)]
    fake_llm.usages = [{"tokens_in": 1500, "tokens_out": 3200}]

    resp = await client.post("/opponent/sessions", json=_payload())

    assert resp.status_code == 201
    waited, ok = await _llm_calls(db_session, uuid.UUID(resp.json()["opponent_session_id"]))
    assert waited.failure_kind == "rate_limited" and waited.rate_limit_wait_ms == 6500
    assert (ok.tokens_in, ok.tokens_out, ok.rate_limit_wait_ms) == (1500, 3200, None)


async def test_key_repairs_are_stored(client, db_session, fake_llm):
    from tests.conftest import SchemaRejected

    data = json.loads(json.dumps(VALID_CASE_FILE))
    data["motion_readng"] = data.pop("motion_reading")
    fake_llm.responses = [SchemaRejected(json.dumps(data, ensure_ascii=False))]

    resp = await client.post("/opponent/sessions", json=_payload())

    assert resp.status_code == 201 and len(fake_llm.calls) == 1
    [call] = await _llm_calls(db_session, uuid.UUID(resp.json()["opponent_session_id"]))
    assert call.success and call.failure_kind is None
    assert call.key_repairs["event"] == "key_repaired"
    assert call.key_repairs["renames"] == [{"path": "motion_reading", "from": "motion_readng", "to": "motion_reading"}]
    case_file = await db_session.scalar(select(OpponentCaseFile).where(OpponentCaseFile.session_id == call.session_id))
    assert "motion_reading" in case_file.content and "motion_readng" not in case_file.content
