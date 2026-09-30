"""
Format tran dau — dinh nghia O MOT CHO DUY NHAT (Giai doan 3, dev log muc 3.x "Format tran").

6 luot, turn_index 1..6:
    1 opening  pro | 2 opening  con | 3 rebuttal pro | 4 rebuttal con | 5 closing con | 6 closing pro

Rut gon tu LD (Lincoln-Douglas): moi ben 3 bai; tong ket DAO THU TU (con truoc, pro sau) nhu reply speech cua
WSDC / AP — phe De xuat mo man va cung la phe noi cuoi.

Tu ai_side cua session suy ra luot nao cua AI, luot nao cua learner. Moi ham o day THUAN (khong DB, khong LLM).
"""
from dataclasses import dataclass

from app.core.config import Settings
# Enum dinh nghia o models (dung chung cho cot DB); import lai de noi khac chi can import tu day.
from app.opponent.models import DebateSide, RoundType, Speaker, TurnMode  # noqa: F401


@dataclass(frozen=True)
class TurnSpec:
    turn_index: int
    round_type: RoundType
    side: DebateSide


MATCH_FORMAT: tuple[TurnSpec, ...] = (
    TurnSpec(1, RoundType.OPENING, DebateSide.PRO),
    TurnSpec(2, RoundType.OPENING, DebateSide.CON),
    TurnSpec(3, RoundType.REBUTTAL, DebateSide.PRO),
    TurnSpec(4, RoundType.REBUTTAL, DebateSide.CON),
    TurnSpec(5, RoundType.CLOSING, DebateSide.CON),
    TurnSpec(6, RoundType.CLOSING, DebateSide.PRO),
)
TURN_COUNT = len(MATCH_FORMAT)
_BY_INDEX = {t.turn_index: t for t in MATCH_FORMAT}


class InvalidTurnError(ValueError):
    """turn_index / round_type / nguoi noi khong khop format tran."""


def turn_spec(turn_index: int) -> TurnSpec:
    try:
        return _BY_INDEX[turn_index]
    except KeyError:
        raise InvalidTurnError(f"turn_index {turn_index} khong ton tai (format co luot 1..{TURN_COUNT})") from None


def speaker_of(turn_index: int, ai_side: DebateSide) -> Speaker:
    return Speaker.AI if turn_spec(turn_index).side == ai_side else Speaker.LEARNER


def turns_of(speaker: Speaker, ai_side: DebateSide) -> list[int]:
    return [t.turn_index for t in MATCH_FORMAT if speaker_of(t.turn_index, ai_side) == speaker]


def turn_mode(turn_index: int, ai_side: DebateSide) -> TurnMode:
    """Mode sinh cho luot cua AI. Luot cua learner -> InvalidTurnError."""
    spec = turn_spec(turn_index)
    if spec.side != ai_side:
        raise InvalidTurnError(f"Luot {turn_index} ({spec.round_type.value} {spec.side.value}) la luot cua learner")
    if spec.round_type == RoundType.OPENING:
        # Mo man co 2 tinh huong khac nhau: AI noi dau tien (chua co gi de dap lai) / AI noi sau learner.
        return TurnMode.OPENING_FIRST if turn_index == 1 else TurnMode.OPENING_REPLY
    return TurnMode.REBUTTAL if spec.round_type == RoundType.REBUTTAL else TurnMode.CLOSING


def target_words(round_type: RoundType, settings: Settings) -> int:
    """Do dai muc tieu (so tu) — TURN_TARGET_WORDS_* trong Settings."""
    return {
        RoundType.OPENING: settings.turn_target_words_opening,
        RoundType.REBUTTAL: settings.turn_target_words_rebuttal,
        RoundType.CLOSING: settings.turn_target_words_closing,
    }[round_type]


def word_count(text: str) -> int:
    """So tu = so cum cach nhau boi khoang trang (tieng Viet: moi am tiet 1 'tu', giong cach dem cua Word)."""
    return len(text.split())
