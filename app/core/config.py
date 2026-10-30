"""
Cau hinh service, doc tu bien moi truong (.env).

Cung phong cach voi AI Evaluation service (adpp-ai-service/app/config.py):
pydantic-settings, swap LLM provider chi bang .env, khong sua code.

Khac Evaluation service:
- Co them DATABASE_URL / TEST_DATABASE_URL (service nay luu case file vao PostgreSQL).
- Co tham so rieng cho tung tac vu sinh (CASE_PLAN_TEMPERATURE, ...) vi tac vu
  SINH lap luan can "sang tao" hon tac vu CHAM diem (Evaluation dung 0.2).
"""
from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Bien an toan giua budget planning va nguong "ket" (ghi DB sau khi het budget, do tre he thong...).
STALE_MARGIN_OVER_BUDGET_SECONDS = 60


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ---- Database ----
    # Port 5433 (khong phai 5432) de khong dung Postgres khac dang chay tren may dev.
    database_url: str = "postgresql+asyncpg://adpp:adpp@localhost:5433/ai_generation"
    # DB rieng cho pytest, cung container. Enum/UUID/JSONB la dac thu Postgres nen KHONG test bang SQLite.
    test_database_url: str = "postgresql+asyncpg://adpp:adpp@localhost:5433/ai_generation_test"
    db_echo: bool = False

    # ---- LLM provider selection ----
    llm_provider: str = "groq"  # "openai" | "anthropic" | "gemini" | "groq"

    # ---- OpenAI ----
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # ---- Anthropic ----
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-haiku-4-5-20251001"

    # ---- Gemini ----
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"

    # ---- Groq ----
    groq_api_key: str = ""
    # openai/gpt-oss-120b thay cho llama-3.3-70b-versatile (da bi Groq khai tu,
    # xem AI_DEVELOPMENT_LOG.md muc 3.1 cua Evaluation service).
    groq_model: str = "openai/gpt-oss-120b"

    # ---- LLM call behavior (mac dinh chung) ----
    llm_temperature: float = 0.2
    llm_max_tokens: int = 2000
    llm_timeout_seconds: int = 60
    # Loi mang / timeout / 5xx THOANG QUA (llm.client.is_transient_error): thu lai toi da N lan, cho W x 2^(lan-1) giay
    # (+ jitter). Khong tinh vao so lan thu noi dung; van nam trong budget. Case Planning + luot noi (muc 2.12).
    llm_transient_retries: int = 2
    llm_transient_retry_wait_seconds: float = 2.0

    # ---- Case Planning (AI opponent chuan bi "ho so lap luan" truoc tran) ----
    # Prompt dang dung. v3 va v4 dung chung CaseFile / validator; giu v3 de so sanh batch.
    # case_plan_v6 (thi nghiem motion_type, muc 2.13): CHI dung khi session co motion_type + motion_reading; thieu ->
    # tu dung v5 (prompt_version ghi dung ban da dung). Mac dinh VAN la v5.
    # case_plan_v6b (thi nghiem "ganh nang chung minh", muc 2.15): CHI dung khi session co motion_type + burden_pro +
    # burden_con; thieu -> v5.
    # case_plan_v7 (MAC DINH tu 2026-10-01, muc 2.16-2.17): = v5 + khoi ganh nang chung minh; CHI dung khi session co
    # burden_pro + burden_con (KHONG can motion_type); KHONG co burden -> tu dung case_plan_v5 (giu hanh vi cu).
    # Thi nghiem v7 vs v5 (72 luot / nhanh): lat phe that 2 vs 6, thanh cong 71 vs 72, HIGH 4 vs 2 -> dat ca 3 dieu kien.
    case_plan_prompt_version: Literal[
        "case_plan_v3", "case_plan_v4", "case_plan_v5", "case_plan_v6", "case_plan_v6b", "case_plan_v7"
    ] = "case_plan_v7"
    # Cao hon Evaluation (0.2): can da dang lap luan giua cac lan sinh, nhung
    # khong qua cao de JSON van on dinh.
    case_plan_temperature: float = 0.7
    # Case file dai hon 1 ket qua cham diem; model reasoning (gpt-oss) con tinh
    # ca token suy luan vao max_tokens.
    case_plan_max_tokens: int = 4000
    # So lan thu khi output KHONG HOP LE (sai JSON / sai schema / sai so luan diem).
    # 3 (truoc 2026-09-29: 2): batch v4 co lan chay het luot sau 1 side_flip + 1 schema_rejected (M10 con).
    case_plan_max_attempts: int = 3
    # Gui JSON schema (structured output strict) cho provider ho tro — hien chi Groq. Tat neu model
    # moi khong ho tro (loi 400 tu provider).
    case_plan_use_json_schema: bool = True
    # Muc suy luan gui Groq (gpt-oss: "low" / "medium" / "high"). "medium" GUI TUONG MINH (muc 2.11: so sanh tran low vs
    # medium — low lat phe ca tran). None = khong gui (Groq tu dung mac dinh). Provider khac bo qua. Chi loi goi planner.
    case_plan_reasoning_effort: Literal["low", "medium", "high"] | None = "medium"
    # Loi 429: so lan thu lai toi da + thoi gian cho (thay vong retry trong GroqClient ban goc: 5 lan, 3s).
    # Khong tinh vao case_plan_max_attempts. Moi lan deu ghi opponent_llm_calls.
    case_plan_rate_limit_retries: int = 4
    case_plan_rate_limit_wait_seconds: float = 3.0
    # Tran thoi gian cho TOAN BO Case Planning (moi lan thu + moi lan cho rate-limit).
    # Het budget -> phien FAILED, 504, log "budget_exceeded".
    case_plan_total_budget_seconds: float = 240
    # Session o PLANNING lau hon nguong nay bi coi la "ket" (process chet giua chung) va duoc
    # phep chay lai; chua qua nguong -> 409. Bat buoc > budget + 60s (xem _check_stale_threshold).
    case_plan_stale_after_seconds: float = 360

    # ---- Stance Reviewer (trong tai trung lap kiem tra phe — stance_reviewer.py) ----
    # Provider/model RIENG, doc lap voi model sinh case: model nho/re du cho tac vu phan loai.
    # openai/gpt-oss-20b: da kiem chung tren Groq (JSON schema strict, temperature 0), 2026-09-26.
    # Temperature co dinh = 0 trong code (phan loai can on dinh, khong cau hinh).
    stance_review_enabled: bool = True
    stance_review_provider: str = "groq"
    stance_review_model: str = "openai/gpt-oss-20b"
    # 2000 (truoc: 1500): tokens_out reviewer v1 o batch v4 toi da 1217; replay v2 bi CAT o 1500 (Groq 400 "max
    # completion tokens reached", M04 con medium); v3 con viet them restatement cho moi muc. gpt-oss tinh ca token suy
    # luan. Reviewer dung model rieng (gpt-oss-20b) nen khong an vao TPM cua model sinh case.
    stance_review_max_tokens: int = 2000
    # v1 (MAC DINH tu 2026-09-29, muc 2.4m): chi claim. Replay tren 5 lan thu bi v3 gan co o batch v5: 5/5 pass, 13/13
    # muc khop nhan nguoi. Han che da biet: bao sai M10 (phu dinh mo ho trong claim) — side_flip nay chi ton 1 luot thu
    # vi retry trung tinh (service._attempt_loop).
    # v3: dien dat lai roi hoi "kien nghi manh hon hay yeu di?" — 41/42 tren du lieu thiet ke (muc 2.4l) nhung 3/3 bao sai
    # tren batch v5 (coi ket luan cua chinh muc la "kien nghi"). v2: claim + reasoning (muc 2.4k). Giu ca hai de so sanh.
    stance_review_prompt_version: Literal["stance_review_v1", "stance_review_v2", "stance_review_v3"] = "stance_review_v1"

    # ---- Luot tranh luan (Giai doan 3 — turn_generators.py, match_format.py) ----
    # Bo sinh bai noi cua AI. turn_full_v3 (muc 2.12) = v2 + "KHONG nhac lai / dien giai quy tac, chi dan".
    # turn_full_v2 (muc 2.10) = v1 + rang buoc "khong doc thuat ngu phan tich".
    # turn_full_v1: 1 loi goi JSON (phan tich -> dan y -> bai noi) + case file + ledger + validator (muc 2.9).
    # turn_baseline_v1: chatbot ngay tho, GIU NGUYEN de so sanh.
    turn_generator_version: Literal[
        "turn_baseline_v1", "turn_full_v1", "turn_full_v2", "turn_full_v3", "turn_full_v4", "turn_full_v5",
        "turn_full_v6",
    ] = "turn_full_v6"
    # turn_full_v6 (MAC DINH, muc 2.19) = v5 + sua loi CHEP TIEN DE (ledger doi ten, chi dan trich tu bai MOI, reject
    # premises_reused), chuan hoa "tôi" -> "mình", bo "cố định" o rang buoc cuoi, kiem tra so bo qua "thế kỷ 21" / thu tu.
    # turn_full_v5 (muc 2.18) = v4 + sua loi tu 4 tran thu 30/09 (bo "CỐ ĐỊNH", bo learner_claims khoi output,
    # 3 rang buoc moi, log "tôi" / tieng Anh / cau lap, do dai: chi retry ngoai [0,5x; 1,5x]).
    # turn_full_v4 (muc 2.17) = v3 + ganh nang chung minh cua phe AI (system prompt + khoi rang buoc) khi session co burden.
    # TURN_BURDEN_ENABLED=false -> v4 / v5 KHONG dua burden (ablation 3d); khi do / khi session khong co burden,
    # generator_version ghi "turn_full_v4_noburden" / "turn_full_v5_noburden" / "turn_full_v6_noburden".
    turn_burden_enabled: bool = True
    turn_temperature: float = 0.5
    # CHI turn_full_v* (baseline co dinh 3000 / 2 lan — xem turn_generators.BASELINE_*): JSON + bai noi + token suy luan.
    # 6000 (truoc: 4000): tran 2026-09-30 15:11 co luot 4 tokens_out 3274/4000 va 1 lan output RONG (Groq 400,
    # failed_generation "") o luot 5 — token suy luan dung gan het gioi han (muc 2.10).
    turn_max_tokens: int = 6000
    # Nhu CASE_PLAN_REASONING_EFFORT, cho loi goi sinh bai noi (turn_full_v* va baseline; KHONG ap dung Stance Reviewer).
    turn_reasoning_effort: Literal["low", "medium", "high"] | None = "medium"
    # So lan thu khi output khong hop le (full: JSON / schema / bi cat / bang chung HIGH / lat phe; do dai la loi MEM:
    # toi da 1 lan thu lai). Loi 429 KHONG tinh: luot noi cho bao nhieu lan cung duoc trong TURN_TOTAL_BUDGET_SECONDS
    # (thoi gian cho mac dinh khi provider khong noi: CASE_PLAN_RATE_LIMIT_WAIT_SECONDS).
    turn_max_attempts: int = 3
    # Tran thoi gian cho 1 luot (moi lan goi + moi lan cho 429 / loi mang). Het -> 504. 240 (truoc: 120, muc 2.12):
    # cho 429 cua luot noi CHI bi gioi han boi budget nay (khong gioi han so vong) — tran 17:38 luot 3 that bai vi het 4
    # lan cho 429 (tong 55s) du con budget.
    turn_total_budget_seconds: float = 240
    # Do dai muc tieu (so tu). turn_full_v*: prompt yeu cau [0.8, 1.2] x muc tieu; CHAP NHAN [0.7, 1.25] x muc tieu,
    # ngoai khoang -> thu lai toi da 1 lan roi chap nhan ban gan nhat (loi mem, muc 2.10). Baseline: chi dua vao prompt.
    turn_target_words_opening: int = 400
    turn_target_words_rebuttal: int = 320
    turn_target_words_closing: int = 260

    # ---- Goi y phan bac cho learner (WF-02, hint.py) ----
    # Temperature dung LLM_TEMPERATURE (cau hinh chung, theo spec). 2000 (spec goi y 700): gpt-oss tinh ca token suy luan
    # vao max_tokens; output hint ~300-500 token. Reasoning "low" de nhanh / re. Reviewer (neu bat) dung lai
    # STANCE_REVIEW_* nhu luot noi.
    hint_max_tokens: int = 2000
    hint_reasoning_effort: Literal["low", "medium", "high"] | None = "low"
    # So lan thu khi output khong hop le (JSON / schema / validator / lat phe / reviewer loi). 429 khong tinh.
    hint_max_attempts: int = 3
    # Tran thoi gian cho 1 request hint (moi lan goi + cho 429). Het -> 502 (spec gom moi loi LLM ve 502).
    hint_total_budget_seconds: float = 90

    # ---- App ----
    app_name: str = "ADPP AI Generation Service"
    app_port: int = 8002  # Evaluation service chay 8000

    @model_validator(mode="after")
    def _check_stale_threshold(self) -> "Settings":
        # Planning bi chan cung boi budget, nen phien PLANNING qua (budget + bien) chac chan la
        # phien ket that — request khac chay lai se khong trung voi 1 lan planning con song.
        minimum = self.case_plan_total_budget_seconds + STALE_MARGIN_OVER_BUDGET_SECONDS
        if self.case_plan_stale_after_seconds <= minimum:
            raise ValueError(
                f"CASE_PLAN_STALE_AFTER_SECONDS={self.case_plan_stale_after_seconds} phai > "
                f"CASE_PLAN_TOTAL_BUDGET_SECONDS ({self.case_plan_total_budget_seconds}) + "
                f"{STALE_MARGIN_OVER_BUDGET_SECONDS} = {minimum}"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
