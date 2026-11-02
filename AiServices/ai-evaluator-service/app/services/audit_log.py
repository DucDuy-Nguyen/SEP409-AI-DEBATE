"""
Luu raw output cua MOI lan goi LLM khi cham (ca khi chay trong app that) de truy vet sau nay: truoc day response co
raw_model_output nhung khong ai luu, nen khong doi chieu duoc mot phien da cham (docs/AI_DEVELOPMENT_LOG.md muc 3.16).

Ghi JSONL vao EVAL_AUDIT_LOG_PATH (mac dinh logs/eval_audit.jsonl, de trong = tat). File chua NGUYEN VAN bai noi cua
learner: khong commit (.gitignore), khong tu xoay vong. Loi ghi file KHONG duoc lam hong lan cham.
Lock chi trong 1 process (service chay 1 worker uvicorn); chay nhieu worker thi moi worker nen dung 1 file rieng.
"""
import hashlib
import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path

from app.config import get_settings

logger = logging.getLogger(__name__)

_write_lock = threading.Lock()  # FastAPI chay endpoint dong bo tren threadpool


def record_llm_attempt(
    label: str, attempt: int, system_prompt: str, user_prompt: str, raw_output: str | None, error: Exception | None
) -> None:
    try:
        settings = get_settings()
        if not settings.eval_audit_log_path:
            return

        provider = settings.llm_provider.lower()
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "label": label,
            "attempt": attempt,
            "provider": provider,
            "model": getattr(settings, f"{provider}_model", None),
            "temperature": settings.llm_temperature,
            "system_prompt_sha256": hashlib.sha256(system_prompt.encode("utf-8")).hexdigest(),
            "user_prompt": user_prompt,
            "raw_output": raw_output,
            "error": f"{type(error).__name__}: {error}" if error else None,
        }
        path = Path(settings.eval_audit_log_path)
        with _write_lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning("Khong ghi duoc audit log: %s", e)
