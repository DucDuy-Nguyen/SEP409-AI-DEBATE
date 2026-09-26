"""
Ham dung chung cho moi loai evaluator (argument / round / session):
- extract_json: parse JSON tu output tho cua LLM, chiu duoc markdown fence / text thua.
- call_llm_with_retry: goi LLM, parse JSON, retry 1 lan neu loi — dung chung logic
  retry cho ca 3 cap do de tranh lap code.
"""
import json
import logging
import re
from typing import Callable

logger = logging.getLogger(__name__)

_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


class EvaluationParseError(Exception):
    """LLM tra ve output khong parse duoc thanh JSON hop le sau khi da retry."""


def extract_json(raw_text: str) -> dict:
    """Co gang parse JSON tu output tho cua LLM, chiu duoc markdown fences / text thua."""
    text = raw_text.strip()

    if text.startswith("```"):
        text = re.sub(r"^```(json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = _JSON_BLOCK_RE.search(text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    raise EvaluationParseError(f"Khong the parse JSON tu output cua LLM:\n{raw_text[:500]}")


def call_llm_with_retry(
    generate_fn: Callable[[str], str],
    system_prompt: str,
    user_prompt: str,
    build_result_fn: Callable[[dict, str], object],
    max_attempts: int = 2,
):
    """
    generate_fn(user_prompt) -> raw text tu LLM (da bind san system_prompt/client ben ngoai).
    build_result_fn(parsed_dict, raw_text) -> object ket qua da validate (Pydantic model),
        nem EvaluationParseError / pydantic.ValidationError / TypeError neu du lieu khong hop le.
    """
    from pydantic import ValidationError

    last_error: Exception | None = None
    current_user_prompt = user_prompt

    for attempt in range(max_attempts):
        try:
            raw_output = generate_fn(current_user_prompt)
            parsed = extract_json(raw_output)
            return build_result_fn(parsed, raw_output)
        except (EvaluationParseError, ValidationError, TypeError) as e:
            last_error = e
            logger.warning("Lan thu %d that bai: %s", attempt + 1, e)
            current_user_prompt = (
                current_user_prompt
                + "\n\n[NHAC LAI] CHI tra ve JSON hop le, khong them bat ky text nao khac."
            )

    raise EvaluationParseError(f"That bai sau {max_attempts} lan thu. Loi cuoi: {last_error}")
