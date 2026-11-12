"""Test verify bang LLM gia: rang buoc ep NOT_FOUND, gop lo 5 claim, retry khi JSON loi. Khong can DB, khong goi LLM that."""
import pytest

from app.config import Settings
from app.rag.llm_usage import LLMCallStats
from app.rag.prompts import FACT_MAX_CHARS, build_verify_prompt
from app.rag.schemas import VerdictLabel
from app.rag.verifier import COERCED_PREFIX, DOWNGRADED_PREFIX, NO_FACT_REASON, verify_claims, verify_with_facts
from app.services.json_utils import EvaluationParseError
from tests.rag_fakes import ScriptedLLM, fact, fid, verdict


def _verify_one(llm_label: str, llm_ids, facts=(1, 2)):
    llm = ScriptedLLM({"results": [verdict(1, llm_label, llm_ids)]})
    stats = LLMCallStats()
    [result] = verify_with_facts(["claim A"], [[fact(n) for n in facts]], llm_client=llm, stats=stats)
    return result, stats


@pytest.mark.parametrize("label", ["SUPPORTED", "CONTRADICTED"])
def test_verdict_without_fact_ids_is_coerced_to_not_found(label):
    result, stats = _verify_one(label, [])
    assert result.label == VerdictLabel.NOT_FOUND
    assert result.coerced is True
    assert result.reason.startswith(COERCED_PREFIX)
    assert stats.coerced == 1


# --------------------------------------------------------------------------- fact_id la (muc 3.22)


@pytest.mark.parametrize("label,stance", [("SUPPORTED", "supports"), ("CONTRADICTED", "contradicts")])
def test_unknown_id_plus_valid_fact_with_matching_stance_keeps_label(label, stance):
    # Lan goi that: LLM go sai 1 id (e7279a4c thay vi e7279a4a) nhung van trich dung fact hop le
    item = verdict(1, label, [fid(1), fid(99)], stances={fid(1): stance, fid(99): stance},
                   details=[])
    result, stats = _verify_item(item)
    assert (result.label, result.coerced) == (VerdictLabel(label), False)
    assert result.fact_ids == [fid(1)] and result.dropped_fact_ids == [fid(99)]
    assert stats.coerced == 0


@pytest.mark.parametrize("label,stance", [("SUPPORTED", "contradicts"), ("CONTRADICTED", "supports")])
def test_unknown_id_plus_valid_fact_with_wrong_stance_is_not_found(label, stance):
    item = verdict(1, label, [fid(1), fid(99)], stances={fid(1): stance, fid(99): "supports" if label == "SUPPORTED" else "contradicts"},
                   details=[])
    result, stats = _verify_item(item)
    assert (result.label, result.coerced) == (VerdictLabel.NOT_FOUND, True)
    assert result.dropped_fact_ids == [fid(99)] and stats.coerced == 1


@pytest.mark.parametrize("label", ["SUPPORTED", "CONTRADICTED"])
def test_only_unknown_ids_is_not_found(label):
    result, stats = _verify_one(label, [fid(98), fid(99), fid(99)])
    assert (result.label, result.coerced) == (VerdictLabel.NOT_FOUND, True)
    assert result.fact_ids == [] and result.dropped_fact_ids == [fid(98), fid(99)]


def test_unknown_ids_are_never_fuzzy_matched():
    # id gan dung voi fid(1) (khac 1 ky tu cuoi) van bi bo, khong duoc doan la fid(1)
    near = fid(1)[:-1] + "2"
    assert near != fid(1)
    result, _ = _verify_one("SUPPORTED", [near], facts=(1,))
    assert result.label == VerdictLabel.NOT_FOUND and result.dropped_fact_ids == [near]


def test_legacy_output_without_stance_keeps_label_when_a_valid_id_remains():
    # Output cu chi co "fact_ids" (khong stance): bo id la, con id hop le thi giu nhan
    item = {"claim_index": 1, "label": "SUPPORTED", "fact_ids": [fid(1), fid(99)], "reason": "Khớp.",
            "details": [], "unsupported_details": []}
    result, _ = _verify_item(item)
    assert (result.label, result.dropped_fact_ids) == (VerdictLabel.SUPPORTED, [fid(99)])


def test_valid_contradicting_fact_on_a_detail_wins_over_unknown_fact_id():
    # Muc 3.21.3: chi tiet chi bi fact (hop le) noi trai -> CONTRADICTED, uu tien hon luat ep vi fact_id la
    result, _ = _verify_one("CONTRADICTED", [fid(1), fid(99)])
    assert (result.label, result.coerced, result.fact_ids) == (VerdictLabel.CONTRADICTED, False, [fid(1)])


def test_fact_id_of_another_claim_in_the_batch_is_not_accepted():
    llm = ScriptedLLM({"results": [verdict(1, "SUPPORTED", [fid(2)]), verdict(2, "SUPPORTED", [fid(2)])]})
    first, second = verify_with_facts(["claim A", "claim B"], [[fact(1)], [fact(2)]], llm_client=llm)
    assert (first.label, first.coerced) == (VerdictLabel.NOT_FOUND, True)
    assert (second.label, second.coerced, second.fact_ids) == (VerdictLabel.SUPPORTED, False, [fid(2)])


def test_valid_verdict_is_kept_and_id_case_is_ignored():
    result, stats = _verify_one("contradicted", [fid(2).upper()])
    assert (result.label, result.coerced, result.fact_ids) == (VerdictLabel.CONTRADICTED, False, [fid(2)])
    assert stats.coerced == 0
    assert [f.fact_id for f in result.retrieved] == [fact(1).fact_id, fact(2).fact_id]


def test_not_found_is_never_coerced_and_keeps_only_valid_ids():
    result, _ = _verify_one("NOT_FOUND", [fid(1), fid(99)])
    assert (result.label, result.coerced, result.fact_ids) == (VerdictLabel.NOT_FOUND, False, [fid(1)])


def _verify_item(item: dict, facts=(1, 2)):
    llm = ScriptedLLM({"results": [item]})
    stats = LLMCallStats()
    [result] = verify_with_facts(["claim A"], [[fact(n) for n in facts]], llm_client=llm, stats=stats)
    return result, stats


def test_supported_with_unsupported_details_is_downgraded_to_not_found():
    result, stats = _verify_item(verdict(1, "SUPPORTED", [fid(1)], unsupported=["60 tuổi"]))
    assert (result.label, result.downgraded, result.coerced) == (VerdictLabel.NOT_FOUND, True, False)
    assert result.unsupported_details == ["60 tuổi"]
    assert result.reason.startswith(DOWNGRADED_PREFIX)
    assert (stats.downgraded, stats.coerced) == (1, 0)


def test_detail_without_valid_fact_id_counts_as_unsupported():
    details = [{"detail": "ông Trần Tấn", "fact_ids": [fid(1)]}, {"detail": "60 tuổi", "fact_ids": [fid(99)]}]
    result, stats = _verify_item(verdict(1, "SUPPORTED", [fid(1)], details=details))
    assert (result.label, result.downgraded) == (VerdictLabel.NOT_FOUND, True)
    assert result.unsupported_details == ["60 tuổi"]
    assert [d.fact_ids for d in result.details] == [[fid(1)], []]


def test_fully_supported_claim_keeps_label():
    details = [{"detail": "số thứ tự 27", "fact_ids": [fid(1)]}, {"detail": "ra quầy", "fact_ids": [fid(2)]}]
    result, stats = _verify_item(verdict(1, "SUPPORTED", [fid(1), fid(2)], details=details))
    assert (result.label, result.downgraded, result.unsupported_details) == (VerdictLabel.SUPPORTED, False, [])
    assert stats.downgraded == 0


@pytest.mark.parametrize("label", ["CONTRADICTED", "NOT_FOUND"])
def test_only_supported_is_downgraded(label):
    result, stats = _verify_item(verdict(1, label, [fid(1)], unsupported=["chi tiết thừa"]))
    assert result.label == VerdictLabel(label)
    assert result.downgraded is False and stats.downgraded == 0
    assert result.unsupported_details == ["chi tiết thừa"]


def test_coercion_takes_precedence_over_downgrade():
    result, stats = _verify_item(verdict(1, "SUPPORTED", [], unsupported=["chi tiết thừa"]))
    assert (result.label, result.coerced, result.downgraded) == (VerdictLabel.NOT_FOUND, True, False)
    assert (stats.coerced, stats.downgraded) == (1, 0)


def test_prompt_asks_for_details_and_unsupported_details():
    llm = ScriptedLLM({"results": [verdict(1, "NOT_FOUND")]})
    verify_with_facts(["claim A"], [[fact(1)]], llm_client=llm)
    system_prompt = llm.system_prompts[0]
    assert '"unsupported_details"' in system_prompt and '"details"' in system_prompt
    assert "SUPPORTED: MOI chi tiet deu co trong fact" in system_prompt


def test_claims_are_batched_by_five_with_their_own_facts():
    claims = [f"claim {n}" for n in range(1, 8)]
    llm = ScriptedLLM(
        {"results": [verdict(i, "NOT_FOUND") for i in range(1, 6)]},
        {"results": [verdict(i, "NOT_FOUND") for i in range(1, 3)]},
    )
    stats = LLMCallStats()
    results = verify_with_facts(claims, [[fact(n)] for n in range(1, 8)], llm_client=llm, stats=stats)

    assert llm.calls == 2
    assert [prompt.count("[CLAIM ") for prompt in llm.user_prompts] == [5, 2]
    assert fid(6) in llm.user_prompts[1] and fid(6) not in llm.user_prompts[0]
    assert [r.claim for r in results] == claims
    assert (stats.requests, stats.llm_calls, stats.retries) == (2, 2, 0)
    assert (stats.prompt_tokens, stats.completion_tokens) == (200, 40)


def test_claim_without_facts_is_not_found_without_calling_llm():
    llm = ScriptedLLM({"results": [verdict(1, "SUPPORTED", [fid(2)])]})
    empty, found = verify_with_facts(["claim A", "claim B"], [[], [fact(2)]], llm_client=llm)

    assert (empty.label, empty.reason, empty.coerced) == (VerdictLabel.NOT_FOUND, NO_FACT_REASON, False)
    assert found.label == VerdictLabel.SUPPORTED
    assert llm.calls == 1 and "claim A" not in llm.user_prompts[0]


def test_all_claims_without_facts_never_calls_llm():
    llm = ScriptedLLM()
    results = verify_with_facts(["a", "b"], [[], []], llm_client=llm)
    assert llm.calls == 0 and all(r.label == VerdictLabel.NOT_FOUND for r in results)


@pytest.mark.parametrize(
    "bad_output",
    [
        "khong phai JSON",
        {"results": [verdict(1, "MAYBE", [fid(1)])]},
        {"results": []},
        {"results": [verdict(1, "SUPPORTED", [fid(1)]), verdict(1, "SUPPORTED", [fid(1)])]},
        {"results": [{"claim_index": 1, "label": "SUPPORTED", "fact_ids": [fid(1)], "reason": ""}]},
        {"results": [{**verdict(1, "SUPPORTED", [fid(1)]), "claim_index": True}]},
        {"results": [{key: value for key, value in verdict(1, "SUPPORTED", [fid(1)]).items() if key != "details"}]},
        {"results": [verdict(1, "SUPPORTED", [fid(1)], details=[{"detail": "", "fact_ids": [fid(1)]}])]},
        {"results": [{**verdict(1, "SUPPORTED", [fid(1)]), "unsupported_details": "60 tuổi"}]},
    ],
)
def test_invalid_output_is_retried_through_call_llm_with_retry(bad_output):
    llm = ScriptedLLM(bad_output, {"results": [verdict(1, "SUPPORTED", [fid(1)])]})
    stats = LLMCallStats()
    [result] = verify_with_facts(["claim A"], [[fact(1)]], llm_client=llm, stats=stats)

    assert result.label == VerdictLabel.SUPPORTED
    assert llm.calls == 2 and "[NHAC LAI]" in llm.user_prompts[1]
    assert stats.retries == 1


def test_invalid_output_twice_raises():
    llm = ScriptedLLM("hong", "van hong")
    with pytest.raises(EvaluationParseError):
        verify_with_facts(["claim A"], [[fact(1)]], llm_client=llm)


def test_prompt_cuts_long_fact_and_lists_real_fact_id():
    long_fact = fact(1, "x" * (FACT_MAX_CHARS + 500))
    _, user_prompt = build_verify_prompt(["claim A"], [[long_fact]])
    assert fid(1) in user_prompt
    assert "x" * FACT_MAX_CHARS + "..." in user_prompt
    assert "x" * (FACT_MAX_CHARS + 1) not in user_prompt


def test_system_prompt_forbids_own_knowledge_and_defines_extra_detail_as_not_found():
    llm = ScriptedLLM({"results": [verdict(1, "NOT_FOUND")]})
    verify_with_facts(["claim A"], [[fact(1)]], llm_client=llm)
    system_prompt = llm.system_prompts[0]
    assert "KHONG dung kien thuc rieng" in system_prompt
    assert "Claim co them chi tiet ma fact khong nhac toi -> NOT_FOUND" in system_prompt


class _FakeStore:
    def __init__(self):
        self.calls = []

    def vector_search(self, embedding, topic, k):
        self.calls.append(("vector", topic, k))
        return [fact(1)]

    def keyword_search(self, query, topic, k):
        self.calls.append(("keyword", topic, k))
        return [fact(2)]


class _FakeEmbedder:
    def encode(self, texts):
        return [[0.0] for _ in texts]


def test_verify_claims_retrieves_hybrid_with_top_k_per_claim():
    store = _FakeStore()
    llm = ScriptedLLM({"results": [verdict(1, "SUPPORTED", [fid(1)])]})
    [result] = verify_claims(
        ["claim A"], "education", Settings(rag_top_k=3), llm, store, _FakeEmbedder()
    )
    # Hybrid lay ung vien tu ca 2 nhanh roi cat con top k
    assert {call[0] for call in store.calls} == {"vector", "keyword"}
    assert all(call[1] == "education" for call in store.calls)
    assert len(result.retrieved) == 2 and result.label == VerdictLabel.SUPPORTED


def test_verify_client_uses_its_own_token_limit(monkeypatch):
    from app.rag import verifier

    seen = {}

    def fake_get_llm_client(settings):
        seen["max_tokens"] = settings.llm_max_tokens
        return ScriptedLLM({"results": [verdict(1, "NOT_FOUND")]})

    monkeypatch.setattr(verifier, "get_llm_client", fake_get_llm_client)
    settings = Settings(llm_max_tokens=2000, rag_verify_max_tokens=6000)
    verify_with_facts(["claim A"], [[fact(1)]], settings=settings)
    assert seen["max_tokens"] == 6000
    assert settings.llm_max_tokens == 2000  # Khong doi settings goc


class _RejectingLLM(ScriptedLLM):
    """Lan dau bi provider tu choi (khong co usage), lan sau tra ket qua hop le."""

    def __init__(self, ok_output):
        super().__init__(ok_output)
        self._rejected = False

    def generate(self, system_prompt, user_prompt):
        if not self._rejected:
            self._rejected = True
            raise EvaluationParseError("Groq tu choi output vi JSON khong hop le")
        return super().generate(system_prompt, user_prompt)


def test_rejected_call_is_counted_as_a_retry_without_usage():
    stats = LLMCallStats()
    llm = _RejectingLLM({"results": [verdict(1, "NOT_FOUND")]})
    verify_with_facts(["claim A"], [[fact(1)]], llm_client=llm, stats=stats)
    assert (stats.requests, stats.llm_calls, stats.retries, stats.calls_without_usage) == (1, 2, 1, 1)
    assert stats.prompt_tokens == 100


# --------------------------------------------------------------------------- CONFLICTING (muc 3.21.2)


@pytest.mark.parametrize("llm_label", ["SUPPORTED", "CONTRADICTED", "NOT_FOUND"])
def test_supports_and_contradicts_facts_make_conflicting_whatever_llm_label(llm_label):
    item = verdict(1, llm_label, [fid(1), fid(2)], stances={fid(1): "supports", fid(2): "contradicts"})
    result, stats = _verify_item(item)
    assert result.label == VerdictLabel.CONFLICTING
    assert result.fact_stances == {fid(1): "supports", fid(2): "contradicts"}
    assert (result.coerced, result.downgraded) == (False, False)


def test_unknown_fact_id_cannot_create_a_fake_conflict():
    # fid(99) khong nam trong fact cua claim: bi loai truoc khi xet CONFLICTING
    item = verdict(1, "SUPPORTED", [fid(1), fid(99)], stances={fid(1): "supports", fid(99): "contradicts"})
    result, _ = _verify_item(item)
    # id la bi bo; fid(1) hop le "supports" nen giu SUPPORTED (muc 3.22), khong thanh CONFLICTING
    assert result.label == VerdictLabel.SUPPORTED and result.coerced is False
    assert result.fact_stances == {fid(1): "supports"} and result.dropped_fact_ids == [fid(99)]


def test_same_stance_on_all_facts_is_not_conflicting():
    result, _ = _verify_item(verdict(1, "CONTRADICTED", [fid(1), fid(2)]))
    assert result.label == VerdictLabel.CONTRADICTED


def test_llm_cannot_assign_conflicting_by_itself():
    result, _ = _verify_item(verdict(1, "CONFLICTING", [fid(1)], stances={fid(1): "supports"}))
    assert (result.label, result.coerced) == (VerdictLabel.NOT_FOUND, True)


@pytest.mark.parametrize("bad_stance", ["maybe", "", None])
def test_invalid_stance_is_retried(bad_stance):
    bad = verdict(1, "SUPPORTED", [fid(1)])
    bad["cited_facts"][0]["stance"] = bad_stance
    llm = ScriptedLLM({"results": [bad]}, {"results": [verdict(1, "SUPPORTED", [fid(1)])]})
    [result] = verify_with_facts(["claim A"], [[fact(1)]], llm_client=llm)
    assert result.label == VerdictLabel.SUPPORTED and llm.calls == 2


def test_prompt_asks_for_stance_per_cited_fact():
    llm = ScriptedLLM({"results": [verdict(1, "NOT_FOUND")]})
    verify_with_facts(["claim A"], [[fact(1)]], llm_client=llm)
    assert '"cited_facts": [{"fact_id": "<fact_id>", "stance": "supports"}]' in llm.system_prompts[0]
    assert '"contradicts"' in llm.system_prompts[0]


def test_fact_cited_with_two_stances_is_ignored_by_detail_rules():
    # Output that da gap (env-1): cung fact vua "contradicts" (27 m) vua "supports" (bai chua), gan ca 2 chi tiet
    details = [{"detail": "Lóng gỗ dài khoảng 27 m", "fact_ids": [fid(1)]},
               {"detail": "đã được phát hiện trong bãi chứa", "fact_ids": [fid(1)]}]
    item = verdict(1, "CONTRADICTED", [fid(1)], details=details)
    item["cited_facts"] = [{"fact_id": fid(1), "stance": "contradicts"}, {"fact_id": fid(1), "stance": "supports"}]
    llm = ScriptedLLM({"results": [item]})
    [result] = verify_with_facts(["claim A"], [[fact(1)]], llm_client=llm)
    assert llm.calls == 1  # khong retry
    assert result.fact_stances == {}  # fact mo ho khong dung de xet chi tiet
    assert result.label == VerdictLabel.CONTRADICTED  # giu nhan LLM qua luat cu (fact_id hop le)



# --------------------------------------------------------------------------- xet theo chi tiet (muc 3.21.3)


@pytest.mark.parametrize("llm_label", ["SUPPORTED", "CONTRADICTED", "NOT_FOUND"])
def test_robot_shoebox_case_fact_matching_other_detail_does_not_hide_wrong_number(llm_label):
    # "Robot Iris to bang hop dung giay va pin khoang 70 gio": fact 1 khop "hop dung giay", fact 2 ghi pin 50 gio
    details = [{"detail": "kích thước bằng hộp đựng giày", "fact_ids": [fid(1)]},
               {"detail": "thời lượng pin khoảng 70 giờ", "fact_ids": [fid(2)]}]
    item = verdict(1, llm_label, [fid(1), fid(2)], details=details,
                   stances={fid(1): "supports", fid(2): "contradicts"})
    result, _ = _verify_item(item)
    assert result.label == VerdictLabel.CONTRADICTED


@pytest.mark.parametrize("llm_label", ["SUPPORTED", "CONTRADICTED", "NOT_FOUND"])
def test_68_vs_69_on_the_same_detail_is_conflicting(llm_label):
    # "68 hoc sinh dat giai": fact 1 ghi 68, fact 2 (bai khac) ghi 69 — cung 1 chi tiet
    details = [{"detail": "68 học sinh đạt giải", "fact_ids": [fid(1), fid(2)]}]
    item = verdict(1, llm_label, [fid(1), fid(2)], details=details,
                   stances={fid(1): "supports", fid(2): "contradicts"})
    result, _ = _verify_item(item)
    assert result.label == VerdictLabel.CONFLICTING


def test_wrong_detail_wins_over_conflicting_detail():
    details = [{"detail": "68 học sinh đạt giải", "fact_ids": [fid(1), fid(2)]},
               {"detail": "25 giải nhì", "fact_ids": [fid(2)]}]
    item = verdict(1, "SUPPORTED", [fid(1), fid(2)], details=details,
                   stances={fid(1): "supports", fid(2): "contradicts"})
    result, _ = _verify_item(item)
    assert result.label == VerdictLabel.CONTRADICTED


def test_contradicting_fact_not_attached_to_any_detail_keeps_old_rules():
    # Fact 2 noi trai nhung khong gan voi chi tiet nao: khong co chi tiet sai, giu nhan LLM qua luat cu
    details = [{"detail": "kích thước bằng hộp đựng giày", "fact_ids": [fid(1)]}]
    item = verdict(1, "SUPPORTED", [fid(1), fid(2)], details=details,
                   stances={fid(1): "supports", fid(2): "contradicts"})
    result, _ = _verify_item(item)
    assert result.label == VerdictLabel.SUPPORTED


def test_unknown_fact_on_a_detail_cannot_make_it_wrong():
    details = [{"detail": "thời lượng pin khoảng 70 giờ", "fact_ids": [fid(99)]}]
    item = verdict(1, "NOT_FOUND", [fid(99)], details=details, stances={fid(99): "contradicts"})
    result, _ = _verify_item(item)
    assert result.label == VerdictLabel.NOT_FOUND
