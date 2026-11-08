"""Test tach claim + pipeline bang LLM gia: gioi han 5 claim, khong claim thi khong verify. Khong can DB."""
import pytest

from app.config import Settings
from app.rag import pipeline
from app.rag.claim_extractor import extract_claims
from app.rag.llm_usage import LLMCallStats
from app.rag.schemas import ClaimType, VerdictLabel
from tests.rag_fakes import ScriptedLLM, fact, fid, verdict


def _claims(n: int) -> dict:
    return {"claims": [{"text": f"Claim so {i}.", "claim_type": "statistic"} for i in range(1, n + 1)]}


def test_extract_caps_claims_at_rag_max_claims():
    llm = ScriptedLLM(_claims(7))
    claims = extract_claims("Lap luan co nhieu so lieu.", "Kien nghi", Settings(rag_max_claims=5), llm)
    assert [c.text for c in claims] == [f"Claim so {i}." for i in range(1, 6)]
    assert claims[0].claim_type == ClaimType.STATISTIC
    assert "Toi da 5 claim" in llm.system_prompts[0]


def test_extract_respects_a_smaller_limit():
    llm = ScriptedLLM(_claims(4))
    assert len(extract_claims("Lap luan.", "Kien nghi", Settings(rag_max_claims=2), llm)) == 2


@pytest.mark.parametrize("text", ["", "   \n "])
def test_blank_argument_does_not_call_llm(text):
    llm = ScriptedLLM()
    assert extract_claims(text, "Kien nghi", Settings(), llm) == []
    assert llm.calls == 0


def test_invalid_claim_type_is_retried():
    llm = ScriptedLLM({"claims": [{"text": "A.", "claim_type": "opinion"}]}, _claims(1))
    stats = LLMCallStats()
    assert len(extract_claims("Lap luan.", "Kien nghi", Settings(), llm, stats)) == 1
    assert (stats.requests, stats.llm_calls, stats.retries) == (1, 2, 1)


def test_prompt_contains_motion_and_argument():
    llm = ScriptedLLM(_claims(0))
    extract_claims("Hoc sinh can ngu du gio.", "Nen cam dien thoai trong lop", Settings(), llm)
    assert "Nen cam dien thoai trong lop" in llm.user_prompts[0]
    assert "Hoc sinh can ngu du gio." in llm.user_prompts[0]


class _ExplodingStore:
    """Bat ky truy cap nao toi kho deu la loi: pipeline khong duoc retrieve khi khong co claim."""

    def __getattr__(self, name):
        raise AssertionError(f"Khong duoc goi store.{name}")


def test_pipeline_with_no_claims_skips_verify():
    llm = ScriptedLLM(_claims(0))
    result = pipeline.check_evidence("Toi nghi dieu nay cong bang hon.", "Kien nghi", "education",
                                     Settings(), llm, _ExplodingStore(), object())
    assert llm.calls == 1  # chi lan tach claim
    assert result.claims == [] and result.skipped_reason == pipeline.NO_CLAIM_REASON
    assert result.counts == {"SUPPORTED": 0, "CONTRADICTED": 0, "NOT_FOUND": 0}


def test_pipeline_with_blank_argument_calls_nothing():
    llm = ScriptedLLM()
    result = pipeline.check_evidence("  ", "Kien nghi", "education", Settings(), llm, _ExplodingStore(), object())
    assert llm.calls == 0 and result.skipped_reason == pipeline.NO_CLAIM_REASON


def test_pipeline_verifies_extracted_claims_and_counts_labels(monkeypatch):
    seen = {}

    def fake_verify_claims(claims, topic, settings, llm_client, store, embedder, stats):
        seen["claims"], seen["topic"] = claims, topic
        from app.rag.verifier import verify_with_facts

        return verify_with_facts(claims, [[fact(1)], [fact(2)]], settings, llm_client, stats)

    monkeypatch.setattr(pipeline, "verify_claims", fake_verify_claims)
    llm = ScriptedLLM(_claims(2), {"results": [verdict(1, "SUPPORTED", [fid(1)]), verdict(2, "SUPPORTED", [])]})
    result = pipeline.check_evidence("Lap luan.", "Kien nghi", "technology", Settings(), llm)

    assert seen == {"claims": ["Claim so 1.", "Claim so 2."], "topic": "technology"}
    assert result.counts == {"SUPPORTED": 1, "CONTRADICTED": 0, "NOT_FOUND": 1}
    assert [c.label for c in result.claims] == [VerdictLabel.SUPPORTED, VerdictLabel.NOT_FOUND]
    assert result.skipped_reason is None
