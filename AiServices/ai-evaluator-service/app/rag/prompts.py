"""
Prompt tach claim va verify claim cho RAG Evidence (docs/RAG_STEP2_SPEC.md, muc 3.20 cua dev log).

Giong convention cua cac prompt cham diem: huong dan viet khong dau, ten field JSON giu tieng Anh, noi dung LLM
viet (claim, reason) bang tieng Viet co dau. Verify CHI dua tren fact trong prompt; rang buoc fact_ids duoc kiem
lai bang code trong verifier.py, prompt khong phai lop bao ve duy nhat.
"""
from typing import Sequence

from app.rag.schemas import RetrievedFact

# Cat moi fact dua vao prompt verify de tiet kiem token
FACT_MAX_CHARS = 600

EXTRACT_SYSTEM_PROMPT = """\
Ban la tro ly kiem chung thong tin cho nen tang luyen tranh bien tieng Viet.
Nhiem vu: tu 1 luot lap luan, tach ra cac claim THUC CHUNG co the kiem chung bang du lieu.

[LAY]
- Con so, ty le, so lieu thong ke.
- Su kien da xay ra (ai, lam gi, khi nao, o dau).
- Ket qua nghien cuu, khao sat, bao cao.
- Quy dinh, chinh sach, luat cu the da ban hanh.

[BO QUA]
- Quan diem, gia tri, danh gia: "nen", "can", "cong bang hon", "tot hon", "quan trong".
- Du doan tuong lai: "se tot hon", "se tang".
- Vi du gia dinh: "gia su", "neu nhu", "tuong tuong".
- Cau hoi tu tu, loi keu goi.

[CACH VIET MOI CLAIM]
- Viet lai thanh 1 cau DOC LAP, hieu duoc khi dung rieng: thay dai tu ("no", "ho", "dieu nay") bang chu the ro rang.
- Giu dung noi dung learner noi, KHONG sua cho dung, KHONG them thong tin learner khong noi.
- Chuan hoa so: MOI so viet bang chu deu doi sang chu so, ke ca "mot" ("hai muoi phan tram" -> "20%",
  "ba trieu" -> "3 trieu", "mot trieu ha" -> "1 trieu ha", "nam hai nghin khong tram hai muoi ba" -> "nam 2023").
- Viet so theo dinh dang TIENG VIET: dau CHAM phan cach hang nghin, dau PHAY la dau thap phan
  ("29.383", "12.000 ty dong", "3,5%"). KHONG dung dau phay de phan cach hang nghin ("29,383" la SAI).
  So learner da viet bang chu so thi giu nguyen gia tri, chi sua dau phan cach cho dung dinh dang tren.
- Van ban co the la ban ghi giong noi (khong dau cau, co tu dem "thi", "kieu nhu", "a"): bo tu dem, tach y cho dung.
- Toi da {max_claims} claim, uu tien claim quan trong nhat voi lap luan. Khong co claim thuc chung thi tra mang rong.

[claim_type]
- "statistic": con so, ty le. "event": su kien. "study": nghien cuu, khao sat, bao cao.
- "other_factual": su that kiem chung duoc khac (quy dinh, chinh sach...).

[OUTPUT - CHI tra ve JSON hop le, khong them text nao khac]
{{"claims": [{{"text": "<claim tieng Viet co dau>", "claim_type": "statistic"}}]}}
"""

VERIFY_SYSTEM_PROMPT = """\
Ban la tro ly kiem chung thong tin. Voi moi claim, ban nhan mot danh sach FACT lay tu kho du lieu.
Hay gan nhan cho tung claim CHI DUA TREN CAC FACT DUOC DUA VAO CUA CHINH CLAIM DO.

[QUY TAC BAT BUOC]
- KHONG dung kien thuc rieng cua ban, ke ca khi ban biet claim dung hay sai. Fact khong noi toi thi coi nhu khong biet.
- fact_id CHI duoc lay tu danh sach fact cua chinh claim do, chep dung tung ky tu.
- SUPPORTED va CONTRADICTED bat buoc co it nhat 1 fact trong "cited_facts" lam bang chung.
- Moi fact trong "cited_facts" ghi "stance": "supports" (fact xac nhan claim) hoac "contradicts" (fact noi trai claim).
  Ghi dung lap truong cua TUNG fact, ke ca khi cac fact noi khac nhau.

[CACH LAM CHO TUNG CLAIM]
1. Tach claim thanh cac chi tiet: chu the, con so, thoi gian, dia diem, ten rieng, quan he nhan qua.
   Moi chi tiet la 1 cum ngan chep tu claim. KHONG bo sot chi tiet nao, ke ca chi tiet phu o cuoi cau
   (vd "vi day la van nan nhieu nguoi gap", "60 tuoi", "ong Tran Van A").
2. Voi tung chi tiet, tim fact chua no: ghi fact_id vao "fact_ids" cua chi tiet do. Chi tiet khong co trong
   fact nao thi fact_ids de rong VA chep chi tiet do vao "unsupported_details".
3. Roi moi gan nhan cho ca claim.

[DINH NGHIA NHAN]
- SUPPORTED: MOI chi tiet deu co trong fact va khop (unsupported_details phai rong).
- CONTRADICTED: fact noi RO dieu trai voi claim: sai so, sai thoi gian, sai chu the, dao nguoc quan he.
- NOT_FOUND: fact khong du de khang dinh hay bac bo, ke ca khi fact cung chu de.
  Claim co them chi tiet ma fact khong nhac toi -> NOT_FOUND, KHONG phai SUPPORTED, KHONG phai CONTRADICTED.
  NOT_FOUND khong co nghia la claim sai, chi la kho fact khong du de ket luan.

[reason]
1-2 cau tieng Viet co dau, neu ro diem khop hoac diem vo ly giua claim va fact.

[OUTPUT - CHI tra ve JSON hop le, khong them text nao khac; moi claim dung 1 phan tu]
{"results": [{"claim_index": 1,
  "details": [{"detail": "<chi tiet>", "fact_ids": ["<fact_id>"]}],
  "unsupported_details": ["<chi tiet khong co trong fact nao>"],
  "cited_facts": [{"fact_id": "<fact_id>", "stance": "supports"}],
  "label": "SUPPORTED", "reason": "..."}]}
"""


def build_extract_prompt(argument_text: str, motion: str, max_claims: int) -> tuple[str, str]:
    user_prompt = f"[KIEN NGHI]\n{motion}\n\n[LUOT LAP LUAN]\n{argument_text}"
    return EXTRACT_SYSTEM_PROMPT.format(max_claims=max_claims), user_prompt


def truncate_fact(content: str, max_chars: int = FACT_MAX_CHARS) -> str:
    if len(content) <= max_chars:
        return content
    return content[:max_chars].rstrip() + "..."


def build_verify_prompt(claims: Sequence[str], facts_per_claim: Sequence[Sequence[RetrievedFact]]) -> tuple[str, str]:
    """Moi claim kem fact rieng cua no; claim danh so tu 1 theo thu tu trong lo."""
    blocks = []
    for index, (claim, facts) in enumerate(zip(claims, facts_per_claim), start=1):
        fact_lines = "\n".join(f"- fact_id: {fact.fact_id}\n  noi dung: {truncate_fact(fact.content)}" for fact in facts)
        blocks.append(f"[CLAIM {index}]\n{claim}\n[FACT CUA CLAIM {index}]\n{fact_lines}")
    return VERIFY_SYSTEM_PROMPT, "\n\n".join(blocks)
