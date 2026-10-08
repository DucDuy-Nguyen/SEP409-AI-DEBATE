"""
Fixture dung chung.

DB test: PostgreSQL THAT (database ai_generation_test, cung container docker-compose) —
KHONG dung SQLite vi Enum/UUID/JSONB la dac thu Postgres.
- Dau phien pytest: chay Alembic downgrade base -> upgrade head (dong thoi kiem tra migration).
- Moi test: 1 connection + 1 transaction ngoai cung; AsyncSession dung
  join_transaction_mode="create_savepoint" nen commit() trong service chi release
  savepoint, cuoi test rollback transaction ngoai -> DB sach cho test sau.

LLM: FakeLLMClient / FakeStanceReviewer, khong goi API that, khong can API key.
"""
import json
import os
import re
import time
from collections.abc import AsyncIterator
from pathlib import Path

# Chan goi LLM that: bien moi truong uu tien hon .env trong pydantic-settings, nen xoa key o day
# (TRUOC khi import app) -> test nao lo dung client that se loi ngay thay vi ton token.
# Da tung xay ra: test API goi Stance Reviewer that tren Groq khi chua override dependency.
for _key in ("GROQ_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"):
    os.environ[_key] = ""

import pytest  # noqa: E402

from app.core.config import Settings as _Settings  # noqa: E402

# Test dung gia tri MAC DINH trong code, khong phu thuoc cau hinh may dev: pydantic-settings doc bien moi truong ke ca
# khi _env_file=None, nen xoa moi bien trung ten truong Settings (tru URL DB — de tro toi DB test khac neu can).
for _field in _Settings.model_fields:
    if _field not in ("database_url", "test_database_url") and not _field.endswith("_api_key"):
        os.environ.pop(_field.upper(), None)
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings, get_settings
from app.core.db import get_db
from app.llm.client import LLMClient
from app.main import app
from app.opponent.router import get_llm_client_factory, get_stance_reviewer_factory

ROOT = Path(__file__).resolve().parent.parent
# Settings mac dinh cho test API — khong doc .env (xem fixture `client`). Cung dung cho gia tri test can doc.
TEST_SETTINGS = Settings(_env_file=None)

def _argument(i: int) -> dict:
    return {
        "id": f"A{i}",
        "title": f"Luận điểm {i}",
        "claim": f"Khẳng định {i} của phe AI.",
        "reasoning": f"Cơ chế giải thích vì sao khẳng định {i} đúng.",
        "example": f"Giả sử một học sinh lớp 9 ở Hà Nội gặp tình huống {i}...",
        "impact": f"Tác động {i} tới học sinh và gia đình.",
    }


def make_case_file(n_arguments: int) -> dict:
    """Case file hop le voi dung n_arguments luan diem (medium/hard=3, easy=2)."""
    return {
        "motion_reading": "Xét tác động tổng thể lên học sinh phổ thông Việt Nam.",
        "definitions": [{"term": "bài tập về nhà", "meaning": "Bài được giao làm ngoài giờ học trên lớp."}],
        "arguments": [_argument(i) for i in range(1, n_arguments + 1)],
        "anticipated_opponent_arguments": [
            {"id": "O1", "learner_claim": "Bài tập giúp củng cố kiến thức.", "planned_response": "Củng cố được trên lớp."},
            {"id": "O2", "learner_claim": "Rèn tính tự giác.", "planned_response": "Tự giác rèn bằng cách khác."},
        ],
        "weighing": "Tác hại lên sức khoẻ và thời gian gia đình lớn hơn lợi ích biên.",
    }


# Mac dinh request dung difficulty=medium -> 3 luan diem.
VALID_CASE_FILE = make_case_file(3)


class RateLimited(Exception):
    """Gia lap loi 429 cua SDK (openai.RateLimitError co status_code=429)."""

    status_code = 429


class SchemaRejected(Exception):
    """
    Gia lap loi Groq strict json_schema: 400, code "json_validate_failed", output bi tu choi trong
    body["failed_generation"] (dung cau truc openai.BadRequestError, da thay khi chay that).
    """

    status_code = 400
    code = "json_validate_failed"

    def __init__(self, failed_generation: str = '{"arguments": ["khong phai object"]}'):
        super().__init__("Generated JSON does not match the expected schema.")
        self.body = {"code": self.code, "failed_generation": failed_generation}


class FakeLLMClient(LLMClient):
    """
    Tra ve tung phan tu trong `responses` theo thu tu; phan tu la Exception thi nem ra.
    - delay_seconds: gia lap LLM cham (chay trong thread nhu client that).
    - before_return: callable goi (trong thread) ngay truoc khi tra ket qua — dung de gia lap race.
    """

    provider = "fake"
    model = "fake-model"

    def __init__(self, responses: list[str | Exception] | None = None):
        self.responses = list(responses or [])
        self.calls: list[dict] = []
        self.delay_seconds = 0.0
        self.before_return = None
        # usage gia lap cho moi lan goi THANH CONG (lay lan luot); het -> last_usage = None
        self.usages: list[dict] = []
        # finish_reason gia lap cho moi lan goi THANH CONG (lay lan luot); het -> "stop"
        self.finish_reasons: list[str] = []

    def generate(
        self, system_prompt, user_prompt, temperature=None, max_tokens=None, json_schema=None, reasoning_effort=None
    ) -> str:
        self.last_usage, self.last_finish_reason = None, None
        self.calls.append(
            {
                "system": system_prompt,
                "user": user_prompt,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "json_schema": json_schema,
                "reasoning_effort": reasoning_effort,
            }
        )
        if self.delay_seconds:
            time.sleep(self.delay_seconds)
        if self.before_return is not None:
            self.before_return()
        if not self.responses:
            raise RuntimeError("FakeLLMClient: het response da chuan bi san")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        self._finish()
        return item

    def _finish(self) -> None:
        if self.usages:
            self.last_usage = self.usages.pop(0)
        self.last_finish_reason = self.finish_reasons.pop(0) if self.finish_reasons else "stop"

    def generate_chat(
        self, system_prompt, messages, temperature=None, max_tokens=None, reasoning_effort=None
    ) -> str:
        """Hoi thoai (bai noi trong tran): dung chung hang doi `responses`; ghi {"system", "messages", ...}."""
        self.last_usage, self.last_finish_reason = None, None
        self.calls.append(
            {"system": system_prompt, "messages": [dict(m) for m in messages], "temperature": temperature,
             "max_tokens": max_tokens, "chat": True, "reasoning_effort": reasoning_effort}
        )
        if self.delay_seconds:
            time.sleep(self.delay_seconds)
        if not self.responses:
            raise RuntimeError("FakeLLMClient: het response da chuan bi san")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        self._finish()
        return item


class FakeStanceReviewer(LLMClient):
    """
    Gia lap Stance Reviewer: doc cac id "- [A1] ..." trong prompt va tra JSON review.
    - default_position: position cho moi muc (mac dinh "phan_doi_kien_nghi" = dung phe voi ai_side=con,
      phe mac dinh cua _payload() trong test API).
    - positions: ghi de theo id (vd {"A2": "ung_ho_kien_nghi", "weighing": "khong_ro"}).
    - responses: neu con phan tu thi tra/nem phan tu do TRUOC (de gia lap output sai / loi).
    """

    provider = "fake"
    model = "fake-reviewer"

    def __init__(self, default_position: str = "phan_doi_kien_nghi"):
        self.default_position = default_position
        self.positions: dict[str, str] = {}
        self.responses: list[str | Exception] = []
        self.calls: list[dict] = []
        self.delay_seconds = 0.0

    def generate(
        self, system_prompt, user_prompt, temperature=None, max_tokens=None, json_schema=None, reasoning_effort=None
    ) -> str:
        self.calls.append(
            {"system": system_prompt, "user": user_prompt, "temperature": temperature, "json_schema": json_schema,
             "reasoning_effort": reasoning_effort}
        )
        if self.delay_seconds:
            time.sleep(self.delay_seconds)
        if self.responses:
            item = self.responses.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        ids = re.findall(r"^- \[(\w+)\]", user_prompt, re.MULTILINE)

        def pos(i: str) -> str:
            return self.positions.get(i, self.default_position)

        if '"restatement"' in system_prompt + user_prompt:  # stance_review_v3: restatement -> effect -> reason
            effect = {"ung_ho_kien_nghi": "manh_hon", "phan_doi_kien_nghi": "yeu_di", "khong_ro": "khong_ro"}
            return json.dumps(
                {
                    "arguments": [
                        {"id": i, "restatement": f"dien dat lai {i}", "effect": effect[pos(i)], "reason": "gia lap"}
                        for i in ids
                    ],
                    "weighing": {"restatement": "dien dat lai weighing", "effect": effect[pos("weighing")], "reason": "gia lap"},
                },
                ensure_ascii=False,
            )
        return json.dumps(
            {
                "arguments": [{"id": i, "position": pos(i), "reason": "gia lap"} for i in ids],
                "weighing": {"position": pos("weighing"), "reason": "gia lap"},
            }
        )


@pytest.fixture(scope="session")
def test_database_url() -> str:
    return get_settings().test_database_url


@pytest.fixture(scope="session", autouse=True)
def migrated_test_db(test_database_url: str) -> None:
    # Fixture SYNC: alembic env.py tu goi asyncio.run(), khong duoc chay trong event loop dang chay.
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", test_database_url)
    cfg.attributes["configure_logger"] = False
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")


@pytest.fixture
async def db_session(test_database_url: str) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(test_database_url, poolclass=NullPool)
    async with engine.connect() as conn:
        outer = await conn.begin()
        session = AsyncSession(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()
            await outer.rollback()
    await engine.dispose()


@pytest.fixture(autouse=True)
def no_rate_limit_jitter(monkeypatch):
    """Tat jitter 1-2s khi cho 429 (test nhanh, thoi gian cho xac dinh). Test jitter tu monkeypatch lai."""
    from app.opponent import service, turn_generators

    monkeypatch.setattr(service, "_jitter", lambda: 0.0)
    monkeypatch.setattr(turn_generators, "_jitter", lambda: 0.0)


@pytest.fixture
def fake_llm() -> FakeLLMClient:
    return FakeLLMClient()


@pytest.fixture
def fake_reviewer() -> FakeStanceReviewer:
    return FakeStanceReviewer()


@pytest.fixture
async def client(
    db_session: AsyncSession, fake_llm: FakeLLMClient, fake_reviewer: FakeStanceReviewer
) -> AsyncIterator[AsyncClient]:
    async def _get_db():
        yield db_session

    app.dependency_overrides[get_db] = _get_db
    # Cau hinh MAC DINH trong code, khong doc .env cua may dev (vd CASE_PLAN_MAX_ATTEMPTS trong .env tung lam test
    # phu thuoc ngam vao gia tri 2). Test can cau hinh khac tu ghi de get_settings.
    app.dependency_overrides[get_settings] = lambda: TEST_SETTINGS
    app.dependency_overrides[get_llm_client_factory] = lambda: (lambda: fake_llm)
    # BAT BUOC: khong de test goi Stance Reviewer that (Groq) — da tung xay ra khi chua override.
    app.dependency_overrides[get_stance_reviewer_factory] = lambda: (lambda: fake_reviewer)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac
    finally:
        app.dependency_overrides.clear()
