"""
Khoi [KET QUA KIEM CHUNG] noi vao user prompt cham Argument khi RAG da kiem chung luot lap luan
(docs/RAG_STEP3_SPEC.md, docs/AI_DEVELOPMENT_LOG.md muc 3.21, phuong an C).

Tach rieng khoi app/prompts/evaluator_prompt.py de file do (va config_hash cua scripts/config_fingerprint.py)
giu nguyen: khong co ket qua kiem chung thi prompt cham diem y het truoc. Chi them khoi khi status la "checked"
hoac "no_claims"; "unavailable" thi khong them gi.
"""
from typing import Optional

from app.schemas import EvidenceCheckSummary

_EVIDENCE_RULES = """\
Quy tac dung ket qua kiem chung (CHI anh huong tieu chi Evidence; KHONG dung de cham Logic, Relevance, \
Structure, Persuasiveness):
- CONTRADICTED: so lieu/su kien sai so voi nguon. Phai neu ro trong reasoning cua Evidence va tru diem tuong xung \
muc do (1 so sai nho khac voi bia toan bo).
- SUPPORTED: duoc tinh la bang chung co can cu.
- NOT_FOUND: KHONG coi la sai; kho fact khong du de ket luan. Danh gia nhu binh thuong theo rubric.
- Neu co CONTRADICTED, "suggestions" nen goi y learner sua so lieu kem nguon dung."""

_NO_CLAIMS_TEXT = (
    "Luot lap luan khong co claim thuc chung (so lieu, su kien, nghien cuu) can kiem chung. "
    "Danh gia Evidence nhu binh thuong theo rubric. Thong tin nay KHONG anh huong cac tieu chi khac."
)


def build_evidence_block(summary: Optional[EvidenceCheckSummary]) -> Optional[str]:
    """Khoi them vao cuoi user prompt, hoac None neu khong duoc them gi (prompt giu nguyen tung ky tu)."""
    if summary is None or summary.status == "unavailable":
        return None
    if summary.status == "no_claims" or not summary.claims:
        return f"[KET QUA KIEM CHUNG SO LIEU]\n{_NO_CLAIMS_TEXT}"

    lines = ["[KET QUA KIEM CHUNG SO LIEU] (doi chieu voi kho fact, khong phai y kien cua learner)"]
    for index, claim in enumerate(summary.claims, start=1):
        lines.append(f"{index}. Claim: {claim.claim}\n   Nhan: {claim.label}\n   Ly do: {claim.reason}")
        for citation in claim.citations:
            source = f" (nguon: {citation.citation})" if citation.citation else ""
            lines.append(f"   Fact trich dan: {citation.content}{source}")
    lines.append(_EVIDENCE_RULES)
    return "\n".join(lines)
