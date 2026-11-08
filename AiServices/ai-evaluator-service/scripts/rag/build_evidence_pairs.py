"""
Bo cap lap luan dung / bia cho danh gia RAG Evidence buoc 3 (docs/RAG_STEP3_SPEC.md muc 4). KHONG goi LLM.

Hai buoc:
1. `candidates`: liet ke fact co so lieu cua bai "train" (bai trong kho KHONG co claim nao thuoc split test, de khong
   trung verify_set), status approved, theo tung chu de. Dung de chon fact khi soan lap luan.
2. `build`: doc 15 lap luan goc do Claude soan (docs/rag_eval/evidence_pairs_source.jsonl: argument_true, used_fact_ids,
   numbers = cac so lay tu fact can doi), kiem tra lai voi kho, roi sinh ban bia BANG SCRIPT: doi tung so +/-30-60%
   (lam tron theo do chinh xac cua so goc) hoac doi nam +/-2-5, phan con lai giu nguyen tung chu.
   Ban bia phai khong mau thuan noi tai: nam moi <= 2025, giu thu tu truoc/sau giua cac nam trong cung lap luan,
   so dung sau luong tu chan duoi ("hon", "tren", "ngoai") chi duoc tang (giam thi cau van dung), va
   thoa cac rang buoc khai bao trong `constraints` cua tung cap (vd "{16} >= {10}": so dien gia >= so quoc gia).
   Moi cap thu lan luot seed "42:<pair_id>:<lan thu>" den khi thoa (ghi lai `seed_attempt`).
   Ghi docs/rag_eval/evidence_pairs.jsonl.

Cach dung:
    python scripts/rag/build_evidence_pairs.py candidates --topic education --limit 40
    python scripts/rag/build_evidence_pairs.py build
"""
import argparse
import json
import random
import re
import sys
import unicodedata
from pathlib import Path

SERVICE_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SERVICE_DIR))

sys.stdout.reconfigure(encoding="utf-8")

KB_PATH = SERVICE_DIR / "data" / "vifactcheck_3topics.jsonl"
SOURCE_PATH = SERVICE_DIR / "docs" / "rag_eval" / "evidence_pairs_source.jsonl"
OUTPUT_PATH = SERVICE_DIR / "docs" / "rag_eval" / "evidence_pairs.jsonl"

SEED = 42
MIN_WORDS, MAX_WORDS = 100, 180
CHANGE_MIN, CHANGE_MAX = 0.30, 0.60
YEAR_SHIFT_MIN, YEAR_SHIFT_MAX = 2, 5
MAX_YEAR = 2025  # Nam sau khi doi khong duoc vuot (quyet dinh nguoi dung)
MAX_ATTEMPTS = 1000

# So kieu tieng Viet: 29.383 | 12.000 | 3,5 | 2023
_NUMBER = re.compile(r"\d+(?:\.\d{3})*(?:,\d+)?")
_YEAR = re.compile(r"(?:năm|nam)\s+$", re.IGNORECASE)
# Luong tu chan duoi: "hon 60" giam thanh "hon 38" van la cau dung, nen so sau cac tu nay chi duoc tang
_LOWER_BOUND = re.compile(r"(?:hơn|trên|ngoài)\s+$", re.IGNORECASE)


def train_article_refs() -> set[str]:
    """dataset_ref cua bai co claim nhung KHONG co claim nao thuoc split test."""
    splits: dict[str, set[str]] = {}
    with KB_PATH.open(encoding="utf-8") as lines:
        for line in lines:
            record = json.loads(line)
            splits.setdefault(record["article_id"], set()).add(record["split"])
    return {f"vifactcheck:{article}" for article, seen in splits.items() if "test" not in seen}


# ---------------------------------------------------------------------------
# Sinh so bia
# ---------------------------------------------------------------------------


def parse_vn_number(token: str) -> tuple[float, int, int]:
    """(gia tri, so chu so thap phan, so 0 cuoi cua phan nguyen) cua so viet theo dinh dang tieng Viet."""
    integer, _, decimals = token.partition(",")
    digits = integer.replace(".", "")
    trailing_zeros = len(digits) - len(digits.rstrip("0")) if not decimals and digits.strip("0") else 0
    return float(digits + ("." + decimals if decimals else "")), len(decimals), trailing_zeros


def format_vn_number(value: float, decimals: int) -> str:
    """Dau cham hang nghin, dau phay thap phan; so nguyen co tu 5 chu so tro len moi co dau cham, nhu bao chi."""
    if decimals:
        integer, frac = f"{value:.{decimals}f}".split(".")
        return f"{int(integer):,}".replace(",", ".") + "," + frac
    integer = int(round(value))
    return f"{integer:,}".replace(",", ".") if integer >= 1000 else str(integer)


def fake_number(token: str, rng: random.Random, is_year: bool, is_percent: bool = False) -> str:
    value, decimals, trailing_zeros = parse_vn_number(token)
    if is_year:
        shift = rng.randint(YEAR_SHIFT_MIN, YEAR_SHIFT_MAX) * rng.choice((-1, 1))
        return str(int(value) + shift)
    # Giu do chinh xac cua so goc: 12.000 -> boi so cua 1.000, 29.383 -> so nguyen, 3,5 -> 1 chu so thap phan.
    # Buoc lam tron khong qua 10% gia tri, neu khong "1.000" chi co the thanh 0 hoac 2.000 (ngoai khoang 30-60%).
    if decimals:
        step = 10 ** -decimals
    else:
        step = 10 ** trailing_zeros
        while step > 1 and step > value * 0.1:
            step //= 10
    for _ in range(100):
        factor = 1 + rng.choice((-1, 1)) * rng.uniform(CHANGE_MIN, CHANGE_MAX)
        candidate = round(value * factor / step) * step
        ratio = abs(candidate - value) / value if value else 1
        # Ty le phan tram khong vuot 100 ("117% so truong" se lo ngay la so bia)
        if candidate > 0 and CHANGE_MIN <= ratio <= CHANGE_MAX and not (is_percent and candidate > 100):
            return format_vn_number(candidate, decimals)
    raise ValueError(f"Khong sinh duoc so bia cho {token} trong khoang +/-30-60%")


def is_year_context(text: str, start: int, token: str) -> bool:
    """So 4 chu so dung ngay sau chu "nam" (vd "sinh nam 1879", "vao nam 1915")."""
    return len(token) == 4 and token.isdigit() and 1000 <= int(token) <= 2100 and bool(_YEAR.search(text[:start]))


def make_fake(argument: str, numbers: list[str], rng: random.Random) -> tuple[str, list[dict]]:
    """
    Thay dung tung so trong `numbers` (moi so phai xuat hien dung 1 lan, la mot token so tron ven). Vi tri lay tren
    ban goc va thay 1 lan, de so moi cua lan thay truoc khong bi nham la so goc cua lan sau.
    """
    replacements, changes = [], []
    for token in numbers:
        matches = [m for m in _NUMBER.finditer(argument) if m.group() == token]
        if len(matches) != 1:
            raise ValueError(f"So '{token}' phai xuat hien dung 1 lan trong lap luan, thay {len(matches)}")
        start, end = matches[0].span()
        is_percent = argument[end:end + 1] == "%"
        is_year = is_year_context(argument, start, token)
        new = fake_number(token, rng, is_year, is_percent)
        replacements.append((start, end, new))
        lower_bound = bool(_LOWER_BOUND.search(argument[:start]))
        changes.append({"old": token, "new": new, "kind": "year" if is_year else "number", "lower_bound": lower_bound})
    fake = argument
    for start, end, new in sorted(replacements, reverse=True):
        fake = fake[:start] + new + fake[end:]
    return fake, changes


_CONSTRAINT_TOKEN = re.compile(r"\{([^}]+)\}")
_SAFE_EXPRESSION = re.compile(r"^[\d\s.+\-*/()<>=!]+$")
# Chan luy thua: "9**9**9" lam treo eval


def evaluate_constraint(constraint: str, values: dict[str, str]) -> bool:
    """Rang buoc so hoc tren cac so cua lap luan, vd "{84} >= {68}" hay "20000 <= {110} * 1000000 / {5.000}"."""
    def substitute(match: re.Match) -> str:
        token = match.group(1)
        if token not in values:
            raise ValueError(f"Rang buoc '{constraint}' tham chieu so '{token}' khong co trong numbers")
        return repr(parse_vn_number(values[token])[0])

    expression = _CONSTRAINT_TOKEN.sub(substitute, constraint)
    if not _SAFE_EXPRESSION.match(expression) or "**" in expression:
        raise ValueError(f"Rang buoc khong hop le: {constraint}")
    return bool(eval(expression, {"__builtins__": {}}, {}))  # Chi con so va toan tu, da kiem tra o tren


def violations(changes: list[dict], constraints: list[str]) -> list[str]:
    """Mau thuan noi tai cua ban bia: nam vuot MAX_YEAR, dao thu tu giua cac nam, rang buoc khai bao bi vi pham."""
    problems = []
    years = [(int(c["old"]), int(c["new"])) for c in changes if c["kind"] == "year"]
    problems += [f"nam {new} > {MAX_YEAR}" for _, new in years if new > MAX_YEAR]
    for i, (old_a, new_a) in enumerate(years):
        for old_b, new_b in years[i + 1:]:
            if (old_a > old_b) - (old_a < old_b) != (new_a > new_b) - (new_a < new_b):
                problems.append(f"thu tu nam {old_a}/{old_b} thanh {new_a}/{new_b}")
    problems += [
        f"'hon/tren/ngoai {c['old']}' bi giam thanh {c['new']} (van dung)"
        for c in changes
        if c.get("lower_bound") and parse_vn_number(c["new"])[0] < parse_vn_number(c["old"])[0]
    ]
    fake_values = {c["old"]: c["new"] for c in changes}
    problems += [f"vi pham '{c}'" for c in constraints if not evaluate_constraint(c, fake_values)]
    return problems


def generate_fake(pair_id: str, argument: str, numbers: list[str], constraints: list[str]) -> tuple[str, list[dict], int]:
    """Thu seed rieng cua cap den khi ban bia khong mau thuan noi tai. Tat dinh: cung dau vao -> cung ket qua."""
    true_values = {token: token for token in numbers}
    for constraint in constraints:
        if not evaluate_constraint(constraint, true_values):
            raise ValueError(f"{pair_id}: rang buoc '{constraint}' sai ngay tren ban dung")
    for attempt in range(MAX_ATTEMPTS):
        fake, changes = make_fake(argument, numbers, random.Random(f"{SEED}:{pair_id}:{attempt}"))
        if not violations(changes, constraints):
            return fake, changes, attempt
    raise ValueError(f"{pair_id}: khong sinh duoc ban bia hop le sau {MAX_ATTEMPTS} lan thu")


def unlisted_numbers(argument: str, numbers: list[str], keep: list[str]) -> list[str]:
    """So trong lap luan khong nam trong danh sach can doi, cung khong duoc giu co chu dich (vd ten "COP27")."""
    return [m.group() for m in _NUMBER.finditer(argument) if m.group() not in numbers and m.group() not in keep]


# ---------------------------------------------------------------------------
# Lenh
# ---------------------------------------------------------------------------


def cmd_candidates(topic: str, limit: int) -> None:
    from app.rag.store import FactStore

    refs = train_article_refs()
    with FactStore() as store:
        rows = store._conn.execute(
            """
            SELECT f.id, s.dataset_ref, f.content FROM fact_card f JOIN knowledge_source s ON s.id = f.source_id
            WHERE f.topic = %s AND f.status = 'approved' AND f.content ~ '[0-9]'
            ORDER BY s.dataset_ref, f.created_at
            """,
            (topic,),
        ).fetchall()
    shown = 0
    for fact_id, ref, content in rows:
        if ref not in refs or len(_NUMBER.findall(content)) < 2:
            continue
        print(f"{fact_id} | {ref} | {content[:420]}\n")
        shown += 1
        if shown >= limit:
            break
    print(f"({shown} fact, {len(refs)} bai train trong kho)")


def cmd_build() -> None:
    from app.rag.store import FactStore

    sources = [json.loads(line) for line in SOURCE_PATH.open(encoding="utf-8") if line.strip()]
    refs = train_article_refs()
    pairs = []
    with FactStore() as store:
        for source in sources:
            argument = unicodedata.normalize("NFC", source["argument_true"])
            words = len(argument.split())
            if not MIN_WORDS <= words <= MAX_WORDS:
                raise SystemExit(f"{source['pair_id']}: {words} tu, ngoai {MIN_WORDS}-{MAX_WORDS}")
            facts = store._conn.execute(
                """
                SELECT f.id::text, f.topic, f.status, s.dataset_ref, f.content
                FROM fact_card f JOIN knowledge_source s ON s.id = f.source_id WHERE f.id = ANY(%s::uuid[])
                """,
                (source["used_fact_ids"],),
            ).fetchall()
            if len(facts) != len(source["used_fact_ids"]):
                raise SystemExit(f"{source['pair_id']}: co fact_id khong ton tai trong kho")
            for fact_id, topic, status, ref, _ in facts:
                if topic != source["topic"] or status != "approved" or ref not in refs:
                    raise SystemExit(f"{source['pair_id']}: fact {fact_id} sai topic/status hoac khong thuoc bai train")
            # So theo token tron ven: "84" khong duoc khop nham "1.184"
            fact_numbers = {m.group() for *_, content in facts for m in _NUMBER.finditer(content)}
            for token in source["numbers"]:
                if token not in fact_numbers:
                    raise SystemExit(f"{source['pair_id']}: so '{token}' khong co trong fact da dung")
            # Spec: doi MOI con so cua claim da dung; so con lai phai duoc khai bao giu co chu dich
            leftover = unlisted_numbers(argument, source["numbers"], source.get("keep_numbers", []))
            if leftover:
                raise SystemExit(f"{source['pair_id']}: so {leftover} khong nam trong numbers hay keep_numbers")
            fake, changes, attempt = generate_fake(
                source["pair_id"], argument, source["numbers"], source.get("constraints", [])
            )
            pairs.append(
                {
                    "pair_id": source["pair_id"],
                    "topic": source["topic"],
                    "motion": source["motion"],
                    "side": source["side"],
                    "argument_true": argument,
                    "argument_fake": fake,
                    "used_fact_ids": source["used_fact_ids"],
                    "changes": changes,
                    "constraints": source.get("constraints", []),
                    "seed_attempt": attempt,
                }
            )
    with OUTPUT_PATH.open("w", encoding="utf-8") as output:
        for pair in pairs:
            output.write(json.dumps(pair, ensure_ascii=False) + "\n")
    print(f"Da ghi {len(pairs)} cap vao {OUTPUT_PATH}")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    candidates = sub.add_parser("candidates")
    candidates.add_argument("--topic", choices=("education", "environment", "technology"), required=True)
    candidates.add_argument("--limit", type=int, default=40)
    sub.add_parser("build")
    args = parser.parse_args()
    if args.command == "candidates":
        cmd_candidates(args.topic, args.limit)
    else:
        cmd_build()


if __name__ == "__main__":
    main()
