"""
Parse JSON tu output tho cua LLM.

BAN SAO CO CHU DICH cua extract_json trong adpp-ai-service/app/services/json_utils.py
(khong import cheo). Chi doi ten exception cho hop ngu canh "sinh" thay vi "cham diem".
Khong copy call_llm_with_retry: service nay can ghi log TUNG lan goi LLM vao DB,
nen vong retry nam trong opponent/service.py.
"""
import json
import re

_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


class LLMOutputParseError(Exception):
    """LLM tra ve output khong parse/validate duoc thanh ket qua hop le."""


def extract_json(raw_text: str) -> dict:
    """Co gang parse JSON tu output tho cua LLM, chiu duoc markdown fences / text thua."""
    text = raw_text.strip()

    if text.startswith("```"):
        text = re.sub(r"^```(json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
        match = _JSON_BLOCK_RE.search(text)
        if match:
            try:
                parsed = json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

    if not isinstance(parsed, dict):
        raise LLMOutputParseError(f"Khong the parse JSON object tu output cua LLM:\n{raw_text[:500]}")
    return parsed
