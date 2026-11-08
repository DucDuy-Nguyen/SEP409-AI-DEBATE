"""LLM gia dung chung cho test RAG: tra lan luot cac output soan san va ghi lai prompt nhan duoc."""
import json
from types import SimpleNamespace
from uuid import UUID

from app.rag.schemas import RetrievedFact
from app.services.llm_client import LLMClient


class ScriptedLLM(LLMClient):
    def __init__(self, *outputs, usage=(100, 20)):
        self._outputs = list(outputs)
        self._usage = usage
        self.user_prompts: list[str] = []
        self.system_prompts: list[str] = []

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        self.system_prompts.append(system_prompt)
        self.user_prompts.append(user_prompt)
        if not self._outputs:
            raise AssertionError("LLM gia bi goi nhieu hon so output da soan")
        output = self._outputs.pop(0)
        self.last_usage = (
            None if self._usage is None
            else SimpleNamespace(prompt_tokens=self._usage[0], completion_tokens=self._usage[1])
        )
        return output if isinstance(output, str) else json.dumps(output, ensure_ascii=False)

    @property
    def calls(self) -> int:
        return len(self.user_prompts)


def fact(n: int, content: str = None) -> RetrievedFact:
    return RetrievedFact(fact_id=UUID(int=n), content=content or f"noi dung fact {n}", score=0.5)


def fid(n: int) -> str:
    return str(UUID(int=n))


def verdict(index: int, label: str, fact_ids=(), reason: str = "Fact xác nhận số liệu.") -> dict:
    return {"claim_index": index, "label": label, "fact_ids": list(fact_ids), "reason": reason}
