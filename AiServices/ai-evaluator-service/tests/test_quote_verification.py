"""Test fix C (xac minh trich dan) va audit log raw output. KHONG goi API that."""
import json
import unicodedata

import pytest

from app.config import Settings
from app.schemas import ArgumentTurn, DebateSide, DebateStage, RoundEvaluationRequest, TurnSpeaker
from app.services import audit_log
from app.services.json_utils import EvaluationParseError
from app.services.llm_client import LLMClient
from app.services.quote_verification import quote_in_transcript, verify_weaknesses
from app.services.round_evaluator import evaluate_round

TRANSCRIPT = (
    "Về thực thi: cơ chế yếu là lý do để xây dựng cơ chế, không phải để từ bỏ.\n"
    "IAEA ra đời để giám sát hạt nhân — đó là “công cụ” rất mạnh."
)
TURNS = [
    ArgumentTurn(speaker=TurnSpeaker.LEARNER, text=TRANSCRIPT),
    ArgumentTurn(speaker=TurnSpeaker.OPPONENT, text="Chi phí tuân thủ quá lớn với doanh nghiệp nhỏ."),
]


@pytest.mark.parametrize(
    "quote",
    [
        "cơ chế yếu là lý do để xây dựng cơ chế",
        "  CƠ CHẾ   yếu là\nlý do để xây dựng cơ chế.  ",
        "\"cơ chế yếu là lý do để xây dựng cơ chế\"",
        unicodedata.normalize("NFD", "cơ chế yếu là lý do"),
        "đó là công cụ rất mạnh",
        "IAEA ra đời để giám sát hạt nhân - đó là",
        "Về thực thi ... không phải để từ bỏ",
        "cơ chế yếu là lý do xây dựng cơ chế",  # thieu 1 tu ngan: khop gan dung
    ],
)
def test_quote_found(quote):
    assert quote_in_transcript(quote, TRANSCRIPT)


@pytest.mark.parametrize(
    "quote",
    [
        "đối phương tự xác nhận luận điểm của chúng tôi",  # khong co trong transcript
        "co che yeu la ly do de xay dung co che",  # mat dau tieng Viet la cau khac
        "cơ chế yếu",  # qua ngan
        "",
        "Về thực thi ... một cấu thành hoàn toàn khác",  # moi doan phai khop
        "cơ chế mạnh là lý do để phá bỏ mọi cơ chế cũ",  # dien giai lai, khong phai chep sai
        "cơ chế yếu là lý do để xây dựng cơ chế, phải để từ bỏ",  # mat "không": dao nghia cau
    ],
)
def test_quote_rejected(quote):
    assert not quote_in_transcript(quote, TRANSCRIPT)


def test_verify_keeps_real_quotes_from_either_speaker_and_counts_the_rest():
    raw = [
        {"text": "Thieu so lieu", "quote": "IAEA ra đời để giám sát hạt nhân"},
        {"text": "Chua tra loi", "quote": "Chi phí tuân thủ quá lớn"},
        {"text": "Bia", "quote": "cau nay khong he ton tai trong round"},
        {"text": "Khong co quote"},
        {"text": "   ", "quote": "IAEA ra đời để giám sát"},
        {"text": 5, "quote": "IAEA ra đời để giám sát"},
        "Chuoi tron kieu cu",
    ]

    kept, dropped = verify_weaknesses(raw, TURNS)

    assert [w.text for w in kept] == ["Thieu so lieu", "Chua tra loi"]
    assert dropped == 5


def test_quote_spanning_two_speakers_is_dropped():
    kept, dropped = verify_weaknesses(
        [{"text": "Noi 2 luot", "quote": "công cụ rất mạnh. Chi phí tuân thủ quá lớn"}], TURNS
    )

    assert kept == []
    assert dropped == 1


def test_long_quote_needs_an_exact_match():
    sentence = " ".join(f"tu{i}" for i in range(80))
    assert len(sentence) > 300
    misspelled = sentence.replace("tu40", "tu4")

    assert quote_in_transcript(sentence, sentence)
    assert not quote_in_transcript(misspelled, sentence)


def test_verify_empty_list_drops_nothing():
    assert verify_weaknesses([], TURNS) == ([], 0)


def test_verify_non_list_is_a_format_error_so_the_call_is_retried():
    with pytest.raises(EvaluationParseError):
        verify_weaknesses("khong phai danh sach", TURNS)


class FixedClient(LLMClient):
    def __init__(self, responses: list):
        self.responses = list(responses)

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _payload(weaknesses: list) -> str:
    criteria = [
        {"name": n, "score": 4, "reasoning": "x"} for n in ("Logic", "Evidence", "Relevance", "Structure", "Persuasiveness")
    ]
    return json.dumps({"criteria": criteria, "consistency_note": "On dinh.", "weaknesses": weaknesses})


def _request() -> RoundEvaluationRequest:
    return RoundEvaluationRequest(motion="M", side=DebateSide.PRO, stage=DebateStage.REBUTTAL, turns=TURNS)


def test_round_result_exposes_only_verified_weaknesses_and_score_is_unaffected(caplog):
    client = FixedClient(
        [_payload([{"text": "That", "quote": "IAEA ra đời để giám sát"}, {"text": "Bia", "quote": "khong he co cau nay dau"}])]
    )

    result = evaluate_round(_request(), llm_client=client)

    assert result.weaknesses == ["That"]
    assert result.weakness_evidence[0].quote == "IAEA ra đời để giám sát"
    assert result.dropped_weakness_count == 1
    assert result.round_score == 8.0
    assert "loai 1 diem yeu" in caplog.text


def test_audit_log_records_every_attempt_including_failures(tmp_path, monkeypatch):
    path = tmp_path / "nested" / "audit.jsonl"
    monkeypatch.setattr(audit_log, "get_settings", lambda: Settings(eval_audit_log_path=str(path), _env_file=None))

    evaluate_round(_request(), llm_client=FixedClient(["khong phai json", _payload([])]))

    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [(r["label"], r["attempt"], r["error"] is None) for r in records] == [("round", 1, False), ("round", 2, True)]
    assert records[0]["raw_output"] == "khong phai json"
    assert records[1]["raw_output"] == _payload([])
    assert "IAEA" in records[1]["user_prompt"]


def test_audit_log_records_provider_errors_that_are_not_retried(tmp_path, monkeypatch):
    path = tmp_path / "audit.jsonl"
    monkeypatch.setattr(audit_log, "get_settings", lambda: Settings(eval_audit_log_path=str(path), _env_file=None))

    with pytest.raises(RuntimeError):
        evaluate_round(_request(), llm_client=FixedClient([RuntimeError("provider down")]))

    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["raw_output"] is None
    assert "provider down" in record["error"]


def test_audit_write_failure_does_not_break_grading(tmp_path, monkeypatch):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    monkeypatch.setattr(
        audit_log, "get_settings", lambda: Settings(eval_audit_log_path=str(blocker / "audit.jsonl"), _env_file=None)
    )

    result = evaluate_round(_request(), llm_client=FixedClient([_payload([])]))

    assert result.round_score == 8.0


def test_audit_log_can_be_disabled(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(audit_log, "get_settings", lambda: Settings(eval_audit_log_path="", _env_file=None))

    evaluate_round(_request(), llm_client=FixedClient([_payload([])]))

    assert list(tmp_path.iterdir()) == []
