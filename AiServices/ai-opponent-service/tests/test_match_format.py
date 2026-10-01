"""Format tran (match_format.py) + prompt baseline (turn_generators.build_baseline_prompt) — ham thuan, khong DB/LLM."""
import pytest

from app.core.config import Settings
from app.opponent import match_format as mf
from app.opponent.match_format import InvalidTurnError, RoundType, Speaker, TurnMode
from app.opponent.models import DebateSide, OpponentDifficulty
from app.opponent.turn_generators import SpeechItem, TurnContext, build_baseline_prompt

PRO, CON = DebateSide.PRO, DebateSide.CON
O, R, C = RoundType.OPENING, RoundType.REBUTTAL, RoundType.CLOSING


def test_format_is_fixed_6_turns():
    assert [(t.turn_index, t.round_type, t.side) for t in mf.MATCH_FORMAT] == [
        (1, O, PRO), (2, O, CON), (3, R, PRO), (4, R, CON), (5, C, CON), (6, C, PRO),
    ]


@pytest.mark.parametrize(
    "ai_side,expected",
    [
        (PRO, {1: TurnMode.OPENING_FIRST, 3: TurnMode.REBUTTAL, 6: TurnMode.CLOSING}),
        (CON, {2: TurnMode.OPENING_REPLY, 4: TurnMode.REBUTTAL, 5: TurnMode.CLOSING}),
    ],
)
def test_mode_table_for_both_sides(ai_side, expected):
    assert mf.turns_of(Speaker.AI, ai_side) == sorted(expected)
    assert {t: mf.turn_mode(t, ai_side) for t in mf.turns_of(Speaker.AI, ai_side)} == expected
    learner = [t for t in range(1, 7) if t not in expected]
    assert mf.turns_of(Speaker.LEARNER, ai_side) == learner
    for t in learner:
        assert mf.speaker_of(t, ai_side) == Speaker.LEARNER
        with pytest.raises(InvalidTurnError, match="luot cua learner"):
            mf.turn_mode(t, ai_side)


@pytest.mark.parametrize("bad", [0, 7, -1])
def test_unknown_turn_index(bad):
    with pytest.raises(InvalidTurnError):
        mf.turn_spec(bad)


def test_target_words_from_settings():
    s = Settings(_env_file=None)
    assert [mf.target_words(r, s) for r in (O, R, C)] == [400, 320, 260]
    s2 = Settings(_env_file=None, turn_target_words_rebuttal=300)
    assert mf.target_words(R, s2) == 300


def test_word_count():
    assert mf.word_count("  Tôi   phản đối\nkiến nghị này. ") == 6  # moi am tiet 1 tu
    assert mf.word_count("") == 0


def _ctx(ai_side, turn_index, history=(), case_file=None) -> TurnContext:
    rt = mf.turn_spec(turn_index).round_type
    return TurnContext(
        motion="Nên cấm học sinh sử dụng điện thoại trong trường học", ai_side=ai_side,
        learner_side=CON if ai_side == PRO else PRO, difficulty=OpponentDifficulty.MEDIUM, turn_index=turn_index,
        round_type=rt, target_words=mf.target_words(rt, Settings(_env_file=None)), history=list(history),
        case_file=case_file,
    )


def _speech(t, ai_side, text):
    return SpeechItem(t, mf.turn_spec(t).round_type, mf.speaker_of(t, ai_side), text)


def test_baseline_opening_first_adds_kickoff_user_message():
    system, messages = build_baseline_prompt(TurnMode.OPENING_FIRST, _ctx(PRO, 1))
    assert system.startswith(
        "Bạn là một người tranh luận thuộc phe Đề xuất về kiến nghị "
        "'Nên cấm học sinh sử dụng điện thoại trong trường học'. Hãy tranh luận với người dùng."
    )
    assert "phần mở màn" in system and "Độ dài khoảng 400 từ." in system
    assert system.endswith("Viết bằng tiếng Việt, văn nói, không dùng markdown hay gạch đầu dòng.")
    assert messages == [{"role": "user", "content": "Mời bạn trình bày phần mở màn."}]


def test_baseline_history_roles_second_person_and_no_case_file():
    case_file = {"arguments": [{"claim": "BI MAT CASE FILE"}], "weighing": "WEIGHING BI MAT"}
    history = [_speech(1, CON, "L1"), _speech(2, CON, "AI2"), _speech(3, CON, "L3")]
    system, messages = build_baseline_prompt(TurnMode.REBUTTAL, _ctx(CON, 4, history, case_file))
    assert "Phản đối" in system and "phản bác" in system and "320 từ" in system
    assert messages == [
        {"role": "user", "content": "L1"}, {"role": "assistant", "content": "AI2"}, {"role": "user", "content": "L3"},
    ]
    assert "BI MAT" not in system + str(messages)


def test_baseline_ai_con_closing_right_after_own_rebuttal_gets_closing_kickoff():
    history = [_speech(1, CON, "L1"), _speech(2, CON, "AI2"), _speech(3, CON, "L3"), _speech(4, CON, "AI4")]
    _, messages = build_baseline_prompt(TurnMode.CLOSING, _ctx(CON, 5, history))
    assert [m["role"] for m in messages] == ["user", "assistant", "user", "assistant", "user"]
    assert messages[-1] == {"role": "user", "content": "Mời bạn trình bày phần tổng kết."}


def test_baseline_ai_pro_closing_keeps_opening_kickoff_and_two_learner_speeches():
    history = [_speech(t, PRO, f"S{t}") for t in range(1, 6)]
    system, messages = build_baseline_prompt(TurnMode.CLOSING, _ctx(PRO, 6, history))
    assert messages == [
        {"role": "user", "content": "Mời bạn trình bày phần mở màn."},
        {"role": "assistant", "content": "S1"}, {"role": "user", "content": "S2"},
        {"role": "assistant", "content": "S3"}, {"role": "user", "content": "S4"}, {"role": "user", "content": "S5"},
    ]
    assert "tổng kết" in system and "260 từ" in system


@pytest.mark.parametrize("side", ["pro", "con"])
def test_m01_fixtures_cover_learner_turns_and_length(side):
    from scripts.try_match import load_fixture

    data = load_fixture("M01", side)  # kiem tra dung cac luot cua learner theo format
    assert data["motion"] == "Nên cấm học sinh sử dụng điện thoại trong trường học"
    for s in data["speeches"]:
        assert s["round_type"] == mf.turn_spec(s["turn_index"]).round_type.value
        assert 150 <= mf.word_count(s["text"]) <= 250
