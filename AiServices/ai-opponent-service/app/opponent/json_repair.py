"""
Sua TAT DINH output JSON bi Groq tu choi (400 json_validate_failed) co dang "MANG TACH" — dung chung cho luot noi
(turn_full) va Case Planning. Dev log muc 2.12.

Dang loi that (tran 17:35 luot 4, tran 17:38 luot 3 — gpt-oss-120b): thay vi 1 object, model sinh 1 MANG:
    [ {"learner_claims": [...], "premises": {...}},       <- phan tu dau: object (cac truong dau, dung)
      "target_premise", ":", "Trường đã có phòng máy tính và thư viện", "nếu cần tra cứu thì ...", ...,
      "ai_points", ":", [ ... ],
      "speech_text", ":", "Bạn nói rằng ...", "nên học sinh ...", ... ]
Moi dau phay trong VAN BAN bi bien thanh ranh gioi chuoi -> gia tri bi tach thanh nhieu chuoi lien tiep.

Dung lai object: phan tu dau + moi cap `key, ":"` (key thuoc danh sach truong da biet) va gia tri theo sau; gia tri
gom nhieu chuoi lien tiep -> ghep bang ", " (khoi phuc dau phay) toi key ke tiep / het mang. Khong dung dang -> None
(nguoi goi xu ly nhu schema_rejected). KHONG doan noi dung: chi ghep, khong sua / bo chuoi nao (ke ca chuoi lap lai).
"""
import json
import re
from collections.abc import Iterable

ARRAY_REPAIRED = "array_repaired"
SEPARATOR = ":"
JOINER = ", "


def _parse_array(raw: str | None) -> list | None:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, list) else None


def repair_split_array(raw: str | None, known_keys: Iterable[str]) -> tuple[dict, dict] | None:
    """
    (object da dung lai, thong tin log) hoac None neu khong phai dang mang tach. Thong tin log:
    {"event": "array_repaired", "array_items": n, "keys": [...], "joined": {key: so chuoi da ghep}}.
    """
    items = _parse_array(raw)
    keys = set(known_keys)
    if not items or not isinstance(items[0], dict):
        return None
    obj = dict(items[0])

    def is_key_at(i: int) -> bool:
        return (
            i + 1 < len(items) and isinstance(items[i], str) and items[i] in keys and items[i + 1] == SEPARATOR
        )

    i, added, joined = 1, [], {}
    while i < len(items):
        if not is_key_at(i):
            return None  # rac giua mang / key la -> khong doan
        key = items[i]
        if key in obj:
            return None  # key xuat hien 2 lan -> mo ho
        i += 2
        values = []
        while i < len(items) and not is_key_at(i):
            values.append(items[i])
            i += 1
        if not values:
            return None
        if len(values) == 1:
            obj[key] = values[0]
        elif all(isinstance(v, str) for v in values):
            obj[key] = JOINER.join(values)
            joined[key] = len(values)
        else:
            return None  # nhieu gia tri khong phai chuoi (vd 2 mang) -> khong ghep duoc tat dinh
        added.append(key)
    if not added:
        return None  # mang chi co 1 object: khong phai dang nay
    return obj, {"event": ARRAY_REPAIRED, "array_items": len(items), "keys": added, "joined": joined}
