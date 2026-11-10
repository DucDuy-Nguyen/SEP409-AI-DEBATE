# Spec RAG Evidence — Buoc 4 (WF-01): Dua ket qua kiem chung vao Feedback Report

Owner: Khoa (WF-01). Lien quan: Duy (WF-05, kho fact).
Repo BE: `DucDuy-Nguyen/SEP409-AI-DEBATE` — tao branch `feature/rag-report` tu `origin/feature/rag-evidence` (fa20417).
Repo FE: `philong2206/fe` — branch `feature/evidence-report` tu `main` (2720ad9).

Doc truoc: `docs/RAG_STEP3_SPEC.md`, `app/services/evidence_evaluator.py`, `app/services/round_evaluator.py`,
`app/schemas.py` (RoundEvaluationRequest/Result, EvidenceCheckSummary),
`Services/SystemService.BLL/Services/Debate/Implementations/DebateService.cs` (`EvaluateAndStoreSessionInternalAsync`, `MapJudgementToResponse`),
`Services/SystemService.BLL/DTOs/AI/AiEvaluatorDtos.cs`, `DTOs/Debate/DebateEvaluationDtos.cs`,
FE `src/pages/debater/DebatePractice/DebateResult.tsx`, `src/pages/debater/Debate1v1/Debate1v1Result.tsx`.

## Hien trang (ly do lam buoc nay)

- Buoc 3 chi noi RAG vao `POST /evaluate` (argument-level). Feedback Report cua phien lai di qua
  `POST /evaluate/round` + `POST /evaluate/session` → **khong co kiem chung nao**.
- SystemService khong gui `topic` cho AI Evaluator, khong luu, khong tra ket qua kiem chung.
- FE `DebateResult` khong co cho hien SUPPORTED / CONTRADICTED / NOT_FOUND.
- Muc tieu SRS §3.3.4 + BR-15: report hien ket qua kiem chung tung claim kem fact trich dan, chi dung fact da duyet.

## Quyet dinh da chot

1. Kiem chung lam **o AI Evaluator, trong `/evaluate/round`** (khong goi `/rag/check-evidence` rieng tu C#):
   luat dieu chinh diem Evidence (`adjust_evidence`) nam 1 cho, diem Round → Session tu dong an theo.
2. Kiem chung **tung luot learner** trong round; luot `opponent` KHONG kiem.
3. Luu ket qua trong `AIJudgement.RawResponseJson` (da chua ProRounds/ConRounds) → **khong doi schema SQL Server**.
   Bang ClaimVerification/FactCitation (SRS §3.7.6) de buoc sau (BM02 SR-14, Duy).
4. Phe AI trong AI practice **khong kiem chung** (ton token, khong ai doc).

## Pham vi

- Co: AI practice (WF-01) va P2P 1v1/2v2 (WF-03) — ca hai dung `EvaluateAndStoreSessionInternalAsync`.
- Khong: luong Organizer nap/duyet fact (WF-05, Duy); `/evaluate` argument-level (da xong buoc 3); trang Progress.

## Nguyen tac bat buoc

1. **Khong pha hanh vi cu.** Request `/evaluate/round` khong co `topic` hoac `rag_enabled=False` → prompt, ket qua,
   `config_hash` giong het truoc khi sua; `scripts/config_fingerprint.py --check` van khop. Test cu pass.
2. **RAG loi van ra report.** DB fact tat, embed loi, timeout → round van cham, `evidence_check.status="unavailable"`,
   log warning. Khong bao gio tra 5xx chi vi RAG; C# khong bao gio fail ca phien vi RAG.
3. **Chi fact `approved`** duoc retrieval (BR-15). Kiem lai filter `status='approved'` trong `FactStore`.
4. **Do tre:** N-02 (report ≤ 30 s). Kiem chung chay song song voi luot cham LLM; cac round goi song song tu C#.

## A. AI Evaluator (`AiServices/ai-evaluator-service`)

### A1. Schema (`app/schemas.py`)

- `RoundEvaluationRequest`: them
  - `topic: Optional[Literal["education","environment","technology","society"]] = None`
  - `check_evidence: bool = True` (C# gui `false` cho phe AI)
- Them `TurnEvidenceCheck`: `turn_index: int` (vi tri trong `turns`), `excerpt: str` (≤ 200 ky tu dau luot), `evidence_check: EvidenceCheckSummary`.
- `RoundEvaluationResult`: them `evidence_checks: list[TurnEvidenceCheck] = []`,
  `evidence_score_before: Optional[int]`, `evidence_score_after: Optional[int]`, `evidence_rule_applied: str = ""`.
- `EvidenceCheckSummary.status`: them gia tri `"no_fact_base"` (topic chua co fact approved nao, vd `society` hien tai).
  Mo rong `topic` cua `ArgumentEvaluationRequest` va `/rag/check-evidence` them `"society"` cho dong bo.

### A2. Luong xu ly (`app/services/round_evaluator.py`)

```
evaluate_round(req):
  checks = []
  if settings.rag_enabled and req.topic and req.check_evidence:
      learner_turns = [(i,t) for i,t in enumerate(req.turns) if t.speaker == LEARNER]
      submit song song (ThreadPoolExecutor, dung chung voi luot cham LLM):
          check_evidence(t.text, req.motion, req.topic) cho tung learner turn
      moi future: timeout = rag_round_check_timeout_seconds (moi, mac dinh 20)
          loi/timeout -> EvidenceCheckSummary(status="unavailable", error=...)
      fact store khong co fact approved cho topic -> status="no_fact_base" (khong goi LLM)
  result = cham round nhu cu (prompt KHONG doi o buoc nay)
  labels = gop label cua moi claim trong cac check status "checked"
  if labels:
      after, rule = adjust_evidence(Evidence cua round, labels, settings.rag_evidence_bonus)
      cap nhat criterion Evidence, ghi evidence_score_before/after, evidence_rule_applied
      round_score = tinh lai bang cong thuc hien tai (scoring.py)
      neu co CONTRADICTED: them goi y sua so lieu (contradiction_suggestions) vao suggestions
  result.evidence_checks = checks
```

- Tai dung `summarize`, `adjust_evidence`, `contradiction_suggestions` trong `evidence_evaluator.py`; khong copy logic.
- Import RAG lazy trong nhanh `rag_enabled` (khong import torch khi tat).
- `/evaluate/session`: khong doi; nhan `round_score` da dieu chinh.
- Kiem tra "co fact approved cho topic khong": them `FactStore.count_approved(topic)` (1 query `SELECT count(*)`), cache 5 phut.

### A3. Config (`app/config.py`)

- `rag_round_check_timeout_seconds: float = 20.0`.
- Sua comment `rag_enabled`: nay dieu khien `/rag/*`, `/evaluate` va `/evaluate/round`.

### A4. Test (mock, khong DB, khong LLM that)

1. Khong `topic` / `rag_enabled=False` → prompt va ket qua giong het ban cu, `evidence_checks == []`.
2. `check_evidence=False` → khong goi checker.
3. 2 learner turn + 1 opponent turn → checker goi dung 2 lan, `turn_index` dung.
4. 1 turn CONTRADICTED, Evidence goc 5 → Evidence va `round_score` doi dung theo `adjust_evidence`.
5. Chi NOT_FOUND → diem khong doi.
6. Checker nem loi / qua timeout → round van tra 200, `status="unavailable"`.
7. Topic khong co fact approved → `status="no_fact_base"`, khong goi LLM extract/verify.
8. `config_fingerprint.py --check` khop; toan bo test cu pass.

## B. SystemService (.NET 8)

### B1. DTO

- `AiEvaluatorDtos.cs`
  - `EvaluateRoundRequest`: them `[JsonPropertyName("topic")] string? Topic`, `[JsonPropertyName("check_evidence")] bool CheckEvidence = true`.
  - `EvaluateRoundResponse`: them `evidence_checks` (list `TurnEvidenceCheckDto`), `evidence_score_before`, `evidence_score_after`, `evidence_rule_applied` — tat ca nullable.
  - Them record `TurnEvidenceCheckDto`, `EvidenceCheckSummaryDto`, `EvidenceClaimDto`, `EvidenceCitationDto` map 1-1 voi schema Python (snake_case qua `JsonPropertyName`).
- `DebateEvaluationDtos.cs` → `RoundEvaluationDetailDto`: them `List<TurnEvidenceCheckDto>? EvidenceChecks`, `EvidenceRuleApplied`.

### B2. `EvaluateAndStoreSessionInternalAsync`

- Map topic: `session.Topic?.Category?.Trim().ToLowerInvariant()`; chi gui neu thuoc `education|environment|technology|society`, nguoc lai `null`.
- `CheckEvidence = false` khi phe dang cham la `ParticipantType.AI`.
- Goi round song song: gom tat ca `EvaluateRoundAsync` (moi round × moi phe) vao `Task.WhenAll`, giu thu tu round khi gom lai.
  Sau do 2 `EvaluateSessionAsync` (pro, con) cung `Task.WhenAll`.
- `HttpClient` cua AI Evaluator: timeout ≥ 60 s (kiem lai `Program.cs`).
- Khong doi cach luu: `rawData` da chua `ProRounds`/`ConRounds` → evidence tu dong vao `RawResponseJson`.

### B3. `MapJudgementToResponse`

- Khi build `RoundEvaluationDetailDto` tu `ProRounds`/`ConRounds`: copy `EvidenceChecks`, `EvidenceRuleApplied`.
- Judgement cu (khong co field) → `EvidenceChecks = null`, khong loi.

### B4. Test (`Tests/`)

- Mo rong `DebateAiEvaluatorIntegrationTests` (fake `IAiEvaluatorClient`):
  1. Topic Category "Education" → request round co `topic="education"`; Category la → `topic=null`.
  2. Phien AI practice → request cua phe AI co `check_evidence=false`.
  3. Response co evidence → `GET /evaluation` tra `EvidenceChecks` dung round/phe.
  4. Judgement cu khong co evidence → map khong loi, `EvidenceChecks=null`.

## C. FE (`philong2206/fe`)

### C1. Type va API

- `src/types/ai.types.ts`: them `EvidenceCitation`, `EvidenceClaim`, `EvidenceCheckSummary`, `TurnEvidenceCheck`;
  `RoundEvaluationDetail.evidenceChecks?: TurnEvidenceCheck[]`.
- Khong them API moi: dung `GET /api/debate/{sessionId}/evaluation`.

### C2. Component `src/components/debate/EvidenceCheckPanel.tsx`

- Input: danh sach round cua phe learner (props `rounds`), chi hien khi co it nhat 1 `evidenceChecks`.
- Tren cung: tong so claim theo nhan (chip): Dung nguon / Sai so voi nguon / Khong tim thay trong kho / Nguon chua thong nhat.
- Nhom theo round (Opening, Rebuttal, Closing) → tung luot (excerpt) → tung claim:
  - nhan mau (SUPPORTED xanh, CONTRADICTED do, NOT_FOUND xam, CONFLICTING vang),
  - `reason`,
  - fact trich dan: content rut gon + `citation` (link neu la URL), stance supports/contradicts.
- Neu round co `evidenceRuleApplied` va diem doi → dong nho "Diem Evidence: 5 → 3 (…luat…)".
- Trang thai rieng:
  - `no_claims`: "Luot nay khong co so lieu/su kien can kiem chung."
  - `no_fact_base`: "Chu de nay chua co kho du kien da duyet."
  - `unavailable`: "Tam thoi khong kiem chung duoc" (khong hien `error` tho).
- Ghi chu co dinh duoi panel: "Khong tim thay ≠ sai. Kho du kien chi gom nguon da duoc Organizer duyet."

### C3. Gan vao trang

- `DebateResult.tsx` (AI practice): dat panel sau `ScoreBreakdown`, chi cho phe learner.
- `Debate1v1Result.tsx` (P2P): panel cho phe cua user dang xem; tab xem phe kia neu da co.

### C4. Test (Vitest)

- Render dung so claim moi nhan; an panel khi `evidenceChecks` rong/undefined; hien dung 3 trang thai rieng.

## D. Tieu chi hoan thanh (demo)

1. Topic Education co fact approved: learner noi 1 so lieu dung + 1 so lieu sai → report hien 1 SUPPORTED, 1 CONTRADICTED kem nguon; Evidence round bi ha theo luat.
2. Topic Society: report van ra, panel hien "chua co kho du kien".
3. Tat Postgres fact store: report van ra, panel hien "tam thoi khong kiem chung duoc".
4. Do 5 phien × 3 round: thoi gian tu luc bam Evaluate den luc co report, p95 ≤ 30 s (N-02). Ghi lai so do.
5. Toan bo test cu + moi pass; `config_fingerprint --check` khop.

## E. Tai lieu cap nhat sau khi xong

- `docs/AI_DEVELOPMENT_LOG.md`: muc moi (round-level evidence, song song, do tre do duoc).
- README AI Evaluator: field `topic`, `check_evidence`, `evidence_checks` cua `/evaluate/round`.
- Report 4 §3.1: SD-02 them buoc "check evidence (song song)" va `TurnEvidenceCheck`; Report 5: TC moi cho A4, B4, C4, D1–D4.
- BM02: dong SR-14 doi sang Planned (luu ClaimVerification) neu chua lam.

## Diem dung

- **Dung 1** sau A (pytest + fingerprint + 1 lan goi that `/evaluate/round` co CONTRADICTED): bao ket qua, cho duyet.
- **Dung 2** sau B + C: demo D1–D3 tren local, so do D4. Commit rieng tung repo, khong push khi chua duyet.

## Rui ro

- Do tre: moi luot learner them 1 luot extract + verify LLM. Neu D4 vuot 30 s: giam `rag_max_claims` 5 → 3, hoac chi kiem round Opening + Rebuttal.
- Deploy: AI Evaluator tren Azure Container Apps can them Postgres + pgvector va model bge-m3 (~2 GB RAM). Neu khong kip thi demo local voi `RAG_ENABLED=true`.
- Phu thuoc Duy: can fact approved cho it nhat 1 topic demo (Education); hien kho chi co ViFactCheck education/environment/technology.
