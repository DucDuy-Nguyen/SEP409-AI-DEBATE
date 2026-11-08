"""Dem so lan goi LLM, so lan retry va token cua cac buoc RAG, de script danh gia uoc tinh chi phi."""
from dataclasses import dataclass
from typing import Callable, Optional

from app.services.llm_client import LLMClient


@dataclass
class LLMCallStats:
    requests: int = 0  # So lan goi call_llm_with_retry (1 lan tach claim hoac 1 lo verify)
    llm_calls: int = 0  # So lan goi LLM that, tinh ca lan retry vi JSON loi
    coerced: int = 0  # So claim bi ep ve NOT_FOUND
    prompt_tokens: int = 0
    completion_tokens: int = 0
    calls_without_usage: int = 0  # Provider khong tra usage thi token o tren thieu

    @property
    def retries(self) -> int:
        return self.llm_calls - self.requests

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


def tracking_generate(client: LLMClient, system_prompt: str, stats: Optional[LLMCallStats]) -> Callable[[str], str]:
    """generate_fn cho call_llm_with_retry, cong usage vao stats sau moi lan goi."""

    def generate(user_prompt: str) -> str:
        raw = client.generate(system_prompt, user_prompt)
        if stats is not None:
            stats.llm_calls += 1
            usage = getattr(client, "last_usage", None)
            if usage is None:
                stats.calls_without_usage += 1
            else:
                stats.prompt_tokens += getattr(usage, "prompt_tokens", 0) or 0
                stats.completion_tokens += getattr(usage, "completion_tokens", 0) or 0
        return raw

    return generate
