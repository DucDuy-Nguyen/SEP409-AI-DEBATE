"""
Dich cot `text` cua data/dagstuhl_processed.csv sang tieng Viet, ghi ra file MOI
data/dagstuhl_processed_vi.csv (them cot `text_vi`, giu nguyen moi cot khac,
KHONG ghi de file goc).

Diem nguoi cham duoc giu nguyen vi nguoi cham danh gia ban TIENG ANH goc — ban
dich chi la gan dung, khong phai du lieu tieng Viet do nguoi cham.

Cach chay (tu thu muc goc project):
    python scripts/translate_dagstuhl_to_vi.py            # dich het
    python scripts/translate_dagstuhl_to_vi.py --limit 30 # thu 30 bai dau

Co the chay lai sau khi bi ngat: tien do luu o data/_dagstuhl_vi_partial.json,
bai nao da dich se khong dich lai.
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd

from app.config import get_settings
from app.services.json_utils import EvaluationParseError, call_llm_with_retry
from app.services.llm_client import LLMClient, get_llm_client

DATA_DIR = Path(__file__).parent.parent / "data"
INPUT_PATH = DATA_DIR / "dagstuhl_processed.csv"
OUTPUT_PATH = DATA_DIR / "dagstuhl_processed_vi.csv"
PARTIAL_PATH = DATA_DIR / "_dagstuhl_vi_partial.json"

BATCH_SIZE = 8
URL_PATTERN = re.compile(r"https?://\S+|www\.\S+")

SYSTEM_PROMPT = """You are a professional English-to-Vietnamese translator working on a research dataset of \
short online debate comments (informal, often with typos or poor grammar).

RULES:
- Translate each text into natural Vietnamese. Preserve the meaning, argument structure and level of \
informality. Do NOT improve, correct, summarize, expand or add reasoning: if the original is weak, \
unclear or ungrammatical, the translation must be equally weak or unclear.
- Keep every number, percentage, name, URL and the tag <br/> EXACTLY as in the original.
- Translate every text independently; do not merge texts or use information from other texts.

OUTPUT: only valid JSON, no other text:
{"translations": {"<id>": "<Vietnamese text>", "...": "..."}}
Use exactly the ids given in the input."""


def _build_user_prompt(batch: list[tuple[str, str]]) -> str:
    items = "\n\n".join(f"[id: {item_id}]\n{text}" for item_id, text in batch)
    return f"Translate these {len(batch)} texts:\n\n{items}"


def _validate_translation(source: str, translated: str) -> None:
    if not translated.strip():
        raise EvaluationParseError("ban dich rong")
    for url in URL_PATTERN.findall(source):
        if url not in translated:
            raise EvaluationParseError(f"ban dich lam mat/sua URL: {url}")
    if source.count("<br/>") != translated.count("<br/>"):
        raise EvaluationParseError("ban dich doi so luong the <br/>")


def _build_result(parsed: dict, batch: list[tuple[str, str]]) -> dict[str, str]:
    translations = parsed.get("translations")
    if not isinstance(translations, dict):
        raise EvaluationParseError("thieu object 'translations'")

    expected_ids = {item_id for item_id, _ in batch}
    if set(translations) != expected_ids:
        raise EvaluationParseError(
            f"id tra ve khong khop: thieu {sorted(expected_ids - set(translations))}, "
            f"thua {sorted(set(translations) - expected_ids)}"
        )

    result: dict[str, str] = {}
    for item_id, source in batch:
        translated = translations[item_id]
        if not isinstance(translated, str):
            raise EvaluationParseError(f"ban dich cua {item_id} khong phai chuoi")
        _validate_translation(source, translated)
        result[item_id] = translated.strip()
    return result


def translate_batch(client: LLMClient, batch: list[tuple[str, str]]) -> dict[str, str]:
    user_prompt = _build_user_prompt(batch)
    return call_llm_with_retry(
        generate_fn=lambda up: client.generate(SYSTEM_PROMPT, up),
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        build_result_fn=lambda parsed, raw: _build_result(parsed, batch),
    )


def _load_partial() -> dict[str, str]:
    if PARTIAL_PATH.exists():
        return json.loads(PARTIAL_PATH.read_text(encoding="utf-8"))
    return {}


def _save_partial(done: dict[str, str]) -> None:
    PARTIAL_PATH.write_text(json.dumps(done, ensure_ascii=False, indent=1), encoding="utf-8")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Dich Dagstuhl processed sang tieng Viet (them cot text_vi)")
    parser.add_argument("--limit", type=int, default=None, help="Chi dich N bai dau (de thu)")
    args = parser.parse_args()

    df = pd.read_csv(INPUT_PATH)
    df["text"] = df["text"].fillna("")
    output_path = OUTPUT_PATH
    if args.limit:
        df = df.head(args.limit)
        # Chay thu khong duoc ghi de file day du (316 bai) da dich truoc do.
        output_path = OUTPUT_PATH.with_name("dagstuhl_processed_vi_sample.csv")

    done = _load_partial()
    todo = [(str(r.id), r.text) for r in df.itertuples() if str(r.id) not in done]
    print(f"Tong {len(df)} bai, da dich {len(df) - len(todo)}, con {len(todo)}")

    # Mac dinh service chi cho 2000 token (du cho 1 ket qua cham diem), khong du cho
    # 1 lo dich nhieu bai -> JSON bi cat giua chung. Chi nang gioi han trong script
    # nay, khong dong vao cau hinh chung cua service.
    settings = get_settings().model_copy(update={"llm_max_tokens": 8000, "llm_temperature": 0.0})
    client = get_llm_client(settings)
    for start in range(0, len(todo), BATCH_SIZE):
        batch = todo[start:start + BATCH_SIZE]
        done.update(translate_batch(client, batch))
        _save_partial(done)
        print(f"  {min(start + BATCH_SIZE, len(todo))}/{len(todo)}")

    df = df.copy()
    missing = ~df["id"].astype(str).isin(done)
    if missing.any():
        raise RuntimeError(f"Con {missing.sum()} bai chua co ban dich, khong ghi file")
    df["text_vi"] = df["id"].astype(str).map(done)
    df.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"Da luu: {output_path}")


if __name__ == "__main__":
    main()
