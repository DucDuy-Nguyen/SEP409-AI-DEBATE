# Spec RAG Evidence — Buoc 3: Noi kiem chung vao diem Evidence (Argument-level)

Branch: `feature/rag-evidence` (da co commit 3e1dbb2, b61ea1b tren origin/main)
Thu muc lam viec: `AiServices/ai-evaluator-service/`
Doc truoc: `docs/RAG_STEP1_SPEC.md`, `docs/RAG_STEP2_SPEC.md`, muc 3.19-3.20 cua `docs/AI_DEVELOPMENT_LOG.md`, `app/services/evaluator.py`, `app/prompts/evaluator_prompt.py`, `app/services/scoring.py`, `scripts/config_fingerprint.py`.

## Quyet dinh da chot: phuong an C

Ket qua verify duoc dua vao prompt cham diem de LLM tu can nhac muc do, **cong them 1 luat mem bang code**: neu co it nhat 1 claim CONTRADICTED thi diem Evidence **khong duoc 5/5** (ha ve 4).

Ly do (ghi vao log): false contradiction hien ~2-3% va deu do retrieval lay nham doan → luat cung (vd Evidence <= 2) se tru oan; de LLM tu quyet hoan toan thi khong dam bao va khong chung minh duoc tac dung. Che do thi dau co giam khao nguoi xem lai diem AI.

## Pham vi

- CHI Argument-level (`POST /evaluate`). Round/Session de buoc sau.
- KHONG luu ket qua verify vao DB, KHONG lam luong Organizer nap fact (buoc 4).

## Nguyen tac bat buoc

1. **Khong pha hanh vi cu.** Khi `rag_enabled=False` hoac request khong co `topic`: prompt, ket qua va `config_hash` phai **giong het** truoc khi sua. `scripts/config_fingerprint.py --check` phai van khop hash dong bang `8eaaf59c…ef8d`. Test cu phai pass.
2. **RAG loi thi van cham diem.** DB tat, embed loi, verify loi/timeout → cham nhu khong co RAG, tra `evidence_check.status = "unavailable"` kem ly do, ghi log warning. Khong bao gio tra 5xx chi vi RAG.
3. Luat mem thuc hien bang code sau khi parse ket qua LLM, khong chi dan trong prompt. `overall_score` tinh lai bang `compute_weighted_score` sau khi ha diem.

## 1. Schema (`app/schemas.py`)

- `ArgumentEvaluationRequest`: them `topic: Optional[Literal["education","environment","technology"]] = None`.
- `ArgumentEvaluationResult`: them `evidence_check: Optional[EvidenceCheckSummary] = None`.
- `EvidenceCheckSummary`:
  - `status`: "checked" | "no_claims" | "unavailable"
  - `claims`: list gom `claim`, `label`, `reason`, `citations` (content rut gon <= 300 ky tu + citation/nguon cua fact duoc trich)
  - `counts`: so luong moi nhan
  - `evidence_capped: bool` (luat mem co kich hoat khong), `evidence_score_before_cap: Optional[int]`
  - `error: Optional[str]` (khi unavailable)
- Them `EVIDENCE_CHECK_VERSION = "v1_soft_cap"` va tra kem trong summary.

## 2. Luong xu ly (`app/services/evaluator.py`)

```
evaluate_argument(req):
  evidence_check = None
  if settings.rag_enabled and req.topic:
      try: evidence_check = check_evidence(req.argument, req.motion, req.topic)   # pipeline buoc 2
      except: evidence_check = unavailable(...)
  prompt = build_evaluation_prompt(req, evidence_check)   # khong co evidence_check -> prompt cu y nguyen
  result = call LLM nhu cu
  if evidence_check.status == "checked" and counts.CONTRADICTED > 0 and Evidence == 5:
      Evidence = 4; evidence_capped = True; tinh lai overall_score
  result.evidence_check = summary
```

- Import RAG **lazy** ben trong nhanh `rag_enabled`, de khi tat van khong import torch (giu test hien co).
- Dung `get_default_embedder()` de khong load lai model moi request.

## 3. Prompt (`app/prompts/evaluator_prompt.py`)

Chi them 1 khoi **khi co evidence_check status "checked" hoac "no_claims"**; neu None/unavailable thi prompt giu nguyen tung ky tu.

Noi dung khoi (tieng Viet, ngan gon):
- Liet ke tung claim: nhan + ly do + fact trich dan.
- Quy tac cho tieu chi Evidence:
  - CONTRADICTED: so lieu/su kien sai so voi nguon → phai neu ro trong reasoning cua Evidence va tru diem tuong xung muc do (1 so sai nho khac voi bia toan bo).
  - SUPPORTED: duoc tinh la bang chung co can cu.
  - NOT_FOUND: **khong coi la sai**, kho fact khong du de ket luan; danh gia nhu binh thuong theo rubric.
  - "no_claims": lap luan khong co claim thuc chung can kiem; danh gia Evidence nhu binh thuong theo rubric.
- Ket qua kiem chung **chi anh huong tieu chi Evidence**, khong dung de cham Logic, Relevance, Structure, Persuasiveness.
- Neu co CONTRADICTED, `suggestions` nen goi y learner sua so lieu kem nguon dung.

## 4. Bo danh gia: cap lap luan dung / bia (`scripts/rag/build_evidence_pairs.py`)

Muc tieu chung minh: **khong co RAG, LLM khong phan biet duoc so that va so bia; co RAG thi phan biet duoc.**

- Lay fact tu kho (bai **train** cua 3 chu de, status approved).
- CLI soan **15 lap luan goc** (5/chu de), moi lap luan 100-180 tu, giong learner noi trong tranh bien, dung 2-3 so lieu/su kien **lay dung tu fact trong kho** (ghi lai fact_id da dung). Motion dat theo dung chu de.
- Tu moi lap luan goc sinh **ban bia bang script, khong dung LLM**: doi moi con so cua cac claim da dung (+/-30-60%, lam tron tu nhien) hoac doi nam. Phan con lai giu nguyen tung chu.
- Ghi `docs/rag_eval/evidence_pairs.jsonl`: `pair_id, topic, motion, side, argument_true, argument_fake, used_fact_ids, changes` (danh sach so cu → so moi).
- **DUNG LAI SAU KHI TAO FILE NAY.** In 3 cap mau va bao toi duyet truoc khi chay eval. Khong chay buoc 5 khi toi chua dong y.

## 5. Script danh gia (`scripts/rag/eval_evidence_pairs.py`)

- Cham ca 2 ban (true, fake) cua 15 cap, o 2 dieu kien: **RAG tat** va **RAG bat** → 60 lan cham. Co checkpoint + `--resume` nhu eval_verify.
- Chay `--limit 2` truoc de uoc tinh token; neu uoc tinh toan bo > 400.000 token thi dung lai bao toi.
- Do va in:
  - Diem Evidence trung binh: true vs fake, o tung dieu kien. Chenh lech theo cap (true - fake).
  - Kiem dinh Wilcoxon signed-rank (scipy) tren chenh lech theo cap, tung dieu kien.
  - So cap ma fake bi it nhat 1 claim CONTRADICTED; so lan luat mem kich hoat.
  - So cap ma ban **true** bi CONTRADICTED (bao dong do: tru oan).
  - Tac dong phu: chenh lech trung binh 4 tieu chi con lai giua RAG bat va RAG tat tren cung lap luan (ky vong ~0).
  - Do tre: thoi gian cham trung binh moi lap luan, RAG tat vs bat (tach rieng thoi gian embed, extract, verify, cham).
  - Token: tong va trung binh moi lap luan, tung dieu kien.
- Ghi ket qua vao `data/results/` va chep sang `docs/rag_results/`.

Luu y khi doc: run-to-run variance cua evaluator da biet (~0.56 tren overall, §3.12). Chi chay 1 lan moi dieu kien; neu ket qua sat nguong thi bao toi truoc khi chay lap.

## 6. Viec nho dua vao luon

- Sua thuoc do so trong `scripts/rag/eval_extract.py`: phat hien dinh dang sai kieu "29,383" (dau phay hang nghin). **Chua chay lai eval_extract** (cho toi duyet extract_set).

## 7. Test (mock, khong DB, khong LLM that)

- `rag_enabled=False` / khong co `topic` → prompt giong het ban cu (so sanh chuoi), `evidence_check` = None.
- Pipeline nem loi → van tra ket qua cham, `status="unavailable"`.
- Co CONTRADICTED + Evidence 5 → ha 4, `evidence_capped=True`, overall tinh lai dung.
- Co CONTRADICTED + Evidence <= 4 → khong doi.
- Khong CONTRADICTED → khong doi.
- Toan bo test cu pass; `config_fingerprint.py --check` khop.

## 8. Tai lieu

- Log muc moi 3.21: phuong an C va ly do, luong xu ly, bo cap lap luan, ket qua (sau khi chay), gioi han.
- README: field `topic` va `evidence_check` moi trong API `/evaluate`, vi du request/response.
- Chep spec nay vao `docs/RAG_STEP3_SPEC.md`.

## Khi xong (lan dung thu nhat, sau buoc 4)

Tra ve: file tao/sua, pytest, ket qua `config_fingerprint --check`, 3 cap mau. Dung lai cho toi duyet.

## Khi xong (lan dung thu hai, sau buoc 5)

Tra ve: bang ket qua muc 5, cac cap bat thuong (true bi CONTRADICTED, fake khong bi phat hien), token, do tre, moi cho khac spec. Commit rieng, khong push.
