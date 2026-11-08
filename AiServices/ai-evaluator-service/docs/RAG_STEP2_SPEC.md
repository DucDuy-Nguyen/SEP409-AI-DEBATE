# Spec RAG Evidence — Buoc 2: Tach claim + Verify bang LLM

Branch: `feature/rag-evidence` (da commit buoc 1, da rebase len main)
Thu muc lam viec: `AiServices/ai-evaluator-service/`
Doc truoc: `docs/RAG_STEP1_SPEC.md`, muc 3.19 cua `docs/AI_DEVELOPMENT_LOG.md`.

## Muc tieu buoc nay

1. **Verify**: cho 1 claim + cac fact retrieve duoc → LLM gan nhan SUPPORTED / CONTRADICTED / NOT_FOUND, kem fact_id lam bang chung.
2. **Tach claim**: cho 1 luot lap luan tranh bien → LLM tach ra cac claim thuc chung (so lieu, su kien, nghien cuu) can kiem chung.
3. **Do chat luong** ca 2 phan, dac biet truong hop claim KHONG co trong kho.

**KHONG lam trong buoc nay:** sua prompt cham diem, sua cac endpoint `/evaluate*`, tao bang luu ket qua verify. Viec noi vao diem Evidence de sang buoc 3.

## Nguyen tac thiet ke (bat buoc)

- **Chi verify dua tren fact duoc dua vao prompt, KHONG dung kien thuc rieng cua LLM.** Prompt phai noi ro dieu nay.
- **Rang buoc cung bang code, khong chi bang prompt:** neu LLM tra SUPPORTED hoac CONTRADICTED ma `fact_ids` rong, hoac chua id khong nam trong danh sach fact da dua vao → **ep ve NOT_FOUND** va danh dau `coerced=True`. Dem so lan bi ep trong moi lan eval.
- **NOT_FOUND khong phai la sai.** Nhan nay nghia la "kho fact khong du de ket luan".
- Prompt va `reason` bang **tieng Viet** (giong convention cua evaluator).
- Goi LLM qua `app/services/llm_client.py` va `call_llm_with_retry` trong `app/services/json_utils.py` co san. Khong tao client moi. Ghi audit nhu cac evaluator khac (audit_label rieng: `rag_extract`, `rag_verify`).
- Tiet kiem token (Groq tra phi):
  - Verify **gop nhieu claim trong 1 lan goi** (toi da 5 claim/lan), moi claim kem fact rieng cua no.
  - Moi fact dua vao prompt cat toi da ~600 ky tu.
  - Lap luan khong co claim thuc chung → khong goi verify.

## 1. Module

Them vao `app/rag/`:

```
app/rag/
  prompts.py            # prompt tach claim + prompt verify (tieng Viet)
  claim_extractor.py    # extract_claims(argument_text, motion) -> list[ExtractedClaim]
  verifier.py           # verify_claims(claims, topic) -> list[ClaimVerification]
  pipeline.py           # check_evidence(argument_text, motion, topic) -> EvidenceCheckResult
```

Schema (them vao `app/rag/schemas.py`):
- `ExtractedClaim`: `text`, `claim_type` ("statistic" | "event" | "study" | "other_factual")
- `VerdictLabel`: enum SUPPORTED / CONTRADICTED / NOT_FOUND
- `ClaimVerification`: `claim`, `label`, `fact_ids: list[str]`, `reason`, `coerced: bool`, `retrieved: list[RetrievedFact]`
- `EvidenceCheckResult`: `claims: list[ClaimVerification]`, `counts` (so luong moi nhan), `skipped_reason` (neu khong co claim)

### 1.1 Tach claim (`claim_extractor.py`)
- Toi da 5 claim moi lap luan (hang so dat trong config: `rag_max_claims = 5`).
- Chi lay claim **kiem chung duoc bang du lieu**: con so, ty le, su kien, ket qua nghien cuu, quy dinh/chinh sach cu the.
- **Bo qua** claim gia tri/quan diem/du doan: "nen", "can", "cong bang hon", "se tot hon", vi du gia dinh.
- Moi claim viet lai thanh **cau doc lap** (thay dai tu bang chu the ro rang) de retrieve duoc.
- **Chuan hoa so** truoc khi tra ve: chu so → so ("hai muoi phan tram" → "20%", "ba trieu" → "3 trieu"). Lam bang LLM trong cung prompt, khong viet bo chuyen doi rieng.

### 1.2 Verify (`verifier.py`)
- Moi claim: `retrieve(claim, topic, k=settings.rag_top_k, mode="hybrid")`.
- Gom toi da 5 claim/lan goi LLM. Fact trong prompt danh so theo `fact_id` that.
- LLM tra JSON: moi claim co `label`, `fact_ids`, `reason` (1-2 cau, neu ro diem khop/vo ly).
- Ap rang buoc cung o phan "Nguyen tac thiet ke".
- Dinh nghia nhan trong prompt:
  - SUPPORTED: fact xac nhan noi dung chinh cua claim (so lieu/su kien khop).
  - CONTRADICTED: fact noi ro dieu trai voi claim (sai so, sai thoi gian, sai chu the, dao nguoc quan he).
  - NOT_FOUND: fact khong du de khang dinh hay bac bo, ke ca khi fact cung chu de. **Claim co them chi tiet ma fact khong nhac toi → NOT_FOUND, khong phai CONTRADICTED.**

### 1.3 Endpoint debug
- `POST /rag/check-evidence` nhan `{argument_text, motion, topic}` tra `EvidenceCheckResult`.
- Chi dang ky router khi `rag_enabled=True`. Khi tat, service van khong import torch/RAG (giu test hien co ve dieu nay).

## 2. Bo du lieu danh gia

### 2.1 Verify — tu ViFactCheck (`scripts/rag/build_verify_set.py`)
Ghi `data/eval/verify_set.jsonl`. Tao 2 tap:

**a) in_kb** — claim split **test** cua 3 chu de, du ca 3 nhan. Anh xa nhan: Supported→SUPPORTED, Refuted→CONTRADICTED, NEI→NOT_FOUND. Lay mau phan tang **50 claim/nhan = 150 claim** (seed co dinh = 42), co tham so `--per-label`.

**b) out_of_kb** — claim Supported/Refuted cua cac bai **KHONG nam trong kho** (topic khac 3 chu de, vd The thao, Giai tri, The gioi). Gan topic truy van ngau nhien trong 3 chu de (seed 42). Nhan ky vong **NOT_FOUND** vi kho khong co bai do. Lay **50 claim**.
→ Day la phep thu quan trong nhat: lap luan cua learner thuong khong co bai tuong ung trong kho.

### 2.2 Tach claim — bo tu soan (`data/eval/extract_set.jsonl`, CO commit ban sao vao `docs/rag_eval/extract_set.jsonl`)
Soan **15 lap luan tranh bien** tieng Viet, 5 cho moi chu de, dai 80-200 tu, theo kieu learner noi trong tranh bien. Phan bo:
- 5 lap luan chi co quan diem/gia tri, **khong** co claim thuc chung (ky vong 0 claim).
- 7 lap luan co 1-3 claim thuc chung tron voi quan diem.
- 3 lap luan dang van ban STT: so viet bang chu, khong dau cau, co tu dem ("thi", "kieu nhu", "a").
Moi dong ghi kem `expected_claims` (danh sach cau claim mong doi). **Day la ban nhap de toi duyet lai**, ghi ro dieu nay trong README cua thu muc.

## 3. Script danh gia

### 3.1 `scripts/rag/eval_verify.py`
- Chay verify tren `verify_set.jsonl`. Tham so `--set in_kb|out_of_kb|all`, `--limit`.
- Them che do `--oracle`: thay fact retrieve bang **gold evidence** cua ViFactCheck (chi in_kb, claim co evidence). Muc dich: tach loi do retrieval hay do verify.
- Do va in:
  - Accuracy, macro F1, F1 tung nhan, confusion matrix 3x3 (in_kb, theo tung chu de va tong).
  - out_of_kb: ty le tra dung NOT_FOUND; liet ke cac claim bi gan SUPPORTED/CONTRADICTED sai.
  - **false_contradiction_rate**: ty le claim thuc te SUPPORTED hoac NOT_FOUND bi gan CONTRADICTED. Day la loi nang nhat vi se tru diem oan learner.
  - So lan bi ep NOT_FOUND (`coerced`), so lan retry, tong token neu llm_client tra duoc.
- Ghi `data/results/verify_<mode>_<timestamp>.json` va **chep sang `docs/rag_results/`**.
- Truoc khi chay that, chay `--limit 10` de uoc tinh token/chi phi va in ra; neu uoc tinh toan bo > 300.000 token thi dung lai bao toi.

### 3.2 `scripts/rag/eval_extract.py`
- Chay tach claim tren 15 lap luan.
- Do: so lap luan quan diem bi tach ra claim (ky vong 0); so claim tach ra so voi `expected_claims`; claim co duoc chuan hoa so khong.
- So khop claim tach ra voi expected bang **embedding cosine >= 0.8** (dung embedder co san), khong goi LLM de cham.
- In bang tung lap luan: expected vs extracted, de toi doc tay. Ghi ket qua vao `docs/rag_results/`.

## 4. Test (khong can DB, khong goi LLM that)
- `tests/test_rag_verifier.py`: dung LLM gia (mock) de kiem tra
  - rang buoc ep NOT_FOUND khi fact_ids rong hoac id la;
  - gop claim theo lo 5;
  - parse JSON loi thi retry qua `call_llm_with_retry`.
- `tests/test_rag_extractor.py`: mock LLM, kiem tra gioi han 5 claim, lap luan rong/khong claim thi khong goi verify.
- `tests/test_rag_endpoint.py`: router `/rag/*` khong ton tai khi `rag_enabled=False`.
- Toan bo test cu phai pass.

## 5. Tai lieu
- Dev log: muc moi 3.20 ghi thiet ke verify (rang buoc cung, dinh nghia nhan, gop lo), bo du lieu, va **so lieu ket qua** (in_kb retrieve, in_kb oracle, out_of_kb, extract), kem gioi han.
- README service: cap nhat muc RAG voi thu tu chay script buoc 2 va endpoint debug.
- Chep spec nay vao `docs/RAG_STEP2_SPEC.md`.

## Khi xong, tra ve tom tat gom
1. Danh sach file tao/sua.
2. Bang ket qua eval_verify: in_kb (retrieve), in_kb (oracle), out_of_kb, false_contradiction_rate, so lan coerced.
3. 5 vi du verify sai tieu bieu (claim, nhan dung, nhan du doan, reason cua LLM).
4. Bang ket qua eval_extract.
5. Tong token da dung.
6. pytest.
7. Moi cho tu quyet dinh khac spec, kem ly do.
Khong commit, khong push.
