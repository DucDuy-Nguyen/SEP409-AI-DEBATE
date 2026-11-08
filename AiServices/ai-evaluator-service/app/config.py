"""
Cau hinh service, doc tu bien moi truong (.env).

Ly do dung pydantic-settings: cho phep swap LLM provider (OpenAI / Anthropic / Gemini / Groq)
chi bang cach doi bien moi truong, khong phai sua code — quan trong vi nhom
chua chot duoc dung provider nao (xem README muc "Chon LLM provider").

LLM_PROVIDER dang de default = "groq" theo yeu cau dung tam trong luc chua co
budget OpenAI/Anthropic — Groq co free tier khong can the, toc do rat nhanh.
"""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ---- LLM provider selection ----
    llm_provider: str = "groq"  # "openai" | "anthropic" | "gemini" | "groq"

    # ---- OpenAI ----
    openai_api_key: str = ""
    # gpt-4o-mini: re nhat hien tai ($0.15/$0.60 moi 1M token), phu hop ngan sach sinh vien.
    # gpt-5.4-mini la lua chon moi hon, manh hon nhung dat hon (~5x) — doi khi can.
    openai_model: str = "gpt-4o-mini"

    # ---- Anthropic ----
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-haiku-4-5-20251001"

    # ---- Gemini ----
    gemini_api_key: str = ""
    # gemini-2.5-flash: nhanh, re, co free tier khong can card — phu hop test truoc khi co budget
    gemini_model: str = "gemini-2.5-flash"

    # ---- Groq ----
    groq_api_key: str = ""
    # llama-3.3-70b-versatile: model free-tier pho bien nhat tren Groq hien tai.
    # Groq chay tren LPU rieng, toc do rat nhanh (~300 token/s), free tier khong can the.
    groq_model: str = "llama-3.3-70b-versatile"

    # ---- LLM call behavior ----
    llm_temperature: float = 0.2  # thap vi day la tac vu cham diem, can on dinh khong "sang tao"
    llm_max_tokens: int = 2000
    llm_timeout_seconds: int = 60

    # Luu raw output moi lan cham de truy vet (app/services/audit_log.py); de trong = tat
    eval_audit_log_path: str = "logs/eval_audit.jsonl"
    eval_audit_log_max_bytes: int = 50_000_000  # 0 = khong gioi han
    eval_audit_log_backups: int = 3

    # ---- RAG Evidence (thu nghiem) ----
    # Tat thi service khong import torch/sentence-transformers va khong can DB.
    # Chi dieu khien endpoint debug /rag/* (app/main.py); RAG chua noi vao /evaluate*.
    rag_enabled: bool = False
    # Port 5434: 5433 da duoc ai-opponent-service dung (xem docker-compose.yml)
    rag_database_url: str = "postgresql://adpp:adpp@localhost:5434/ai_evaluation"
    rag_embedding_model: str = "BAAI/bge-m3"
    rag_top_k: int = 5
    rag_max_claims: int = 5  # So claim thuc chung toi da tach tu 1 luot lap luan

    # ---- App ----
    app_name: str = "ADPP AI Evaluator Service"


@lru_cache
def get_settings() -> Settings:
    return Settings()
