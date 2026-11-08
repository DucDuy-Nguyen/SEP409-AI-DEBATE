"""
Ghep cau hoi thanh chuoi cho to_tsquery('simple', ...): cac token noi bang OR, da bo stopword tieng Viet.

Dung OR vi plainto_tsquery la AND: claim dai gan nhu khong doan nao chua du moi tu (docs/AI_DEVELOPMENT_LOG.md muc 3.19).
Ham thuan, khong phu thuoc DB.
"""
import re
import unicodedata
from typing import Optional

# Tu pho bien, xet theo tung am tiet vi tsvector 'simple' tach tieng Viet theo khoang trang.
# Khong co chu so: so (20%, 2023) luon duoc giu lam token. Khong co "ai": token da ve chu thuong
# nen khong phan biet duoc voi "AI" (tri tue nhan tao), tu khoa quan trong cua chu de technology.
VIETNAMESE_STOPWORDS = frozenset(
    {
        "của", "và", "là", "được", "các", "những", "có", "cho", "với", "trong", "này", "đã", "sẽ", "không", "một",
        "để", "khi", "từ", "theo", "về", "tại", "ở", "đó", "đây", "nhiều", "ra", "vào", "trên", "dưới", "sau",
        "trước", "cũng", "như", "nhưng", "hay", "hoặc", "mà", "thì", "bị", "do", "vì", "nên", "nếu", "đến", "còn",
        "rất", "đang", "lại", "chỉ", "phải", "người", "việc", "nói", "cùng", "bởi", "qua", "lên", "xuống", "rằng",
        "gì", "nào", "đều", "vẫn", "mới", "hơn", "nhất", "hai", "ba", "năm", "ông", "bà", "anh", "chị", "họ",
        "tôi", "chúng", "ta", "nó", "thế", "vậy", "sự", "cái", "con", "ngày", "tháng", "lúc", "làm", "giữa", "ngoài",
    }
)

# Cum chu/so, co the noi bang . , - / ben trong (3,5 | 1.000.000 | COVID-19). Dau % cuoi duoc giu lai.
_TOKEN = re.compile(r"[^\W_]+(?:[.,\-/][^\W_]+)*%?")


def _quote(token: str) -> str:
    """Dat trong nhay don de to_tsquery khong hieu ky tu trong token la toan tu."""
    return "'" + token.replace("\\", "\\\\").replace("'", "''") + "'"


def build_or_tsquery(text: str) -> Optional[str]:
    """Tra ve chuoi to_tsquery, hoac None neu khong con token nao (khi do khong can truy van)."""
    tokens = _TOKEN.findall(unicodedata.normalize("NFC", text).lower())
    # dict.fromkeys: bo trung nhung giu thu tu, de chuoi on dinh giua cac lan chay
    kept = dict.fromkeys(token for token in tokens if token not in VIETNAMESE_STOPWORDS)
    return " | ".join(_quote(token) for token in kept) or None
