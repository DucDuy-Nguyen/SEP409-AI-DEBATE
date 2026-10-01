# ADPP AI Generation Service

Module **AI đối thủ tranh biện** (AI Opponent) cho AI Debate Practice Platform (ADPP).
Chạy độc lập, ngang hàng với AI Evaluation service (`adpp-ai-service`, port 8000).
Service này chạy port **8002**.

Tính năng hiện có (Phase 1): **Case Planning** — khi Main Flow tạo phiên, AI đối thủ gọi LLM để
chuẩn bị "case file" (luận điểm, dự đoán luận điểm của learner + hướng phản biện), lưu vào PostgreSQL.
Mỗi phiên đúng 1 case file.

## Cấu trúc

```
app/
  main.py                    # FastAPI app, GET /health
  core/config.py             # Settings đọc từ .env
  core/db.py                 # async engine (asyncpg), dependency get_db
  llm/                       # BẢN SAO có chủ đích provider abstraction từ Evaluation service
  opponent/
    models.py                # ORM: opponent_sessions, opponent_case_files, opponent_llm_calls,
                             #      opponent_speeches, opponent_turns
    schemas.py               # request/response + schema CaseFile
    router.py                # endpoint (chỉ gọi service)
    service.py               # logic Case Planning
    match_format.py          # format trận 6 lượt + mode sinh (MỘT chỗ duy nhất)
    turn_service.py          # POST .../turns: validate, idempotent, lưu bài nói
    turn_generators.py       # interface bộ sinh + turn_baseline_v1 (chatbot ngây thơ, giữ nguyên để so sánh)
    turn_full.py             # turn_full_v3 (mặc định) / v2 / v1: JSON phân tích → dàn ý → bài nói, ledger, validator
    json_repair.py           # sửa tất định JSON "mảng tách" bị Groq từ chối (lượt nói + Case Planning)
    prompts/case_plan_v5.py  # mặc định (CASE_PLAN_PROMPT_VERSION)
    prompts/case_plan_v4.py, case_plan_v3.py  # vẫn chạy được, giữ để so sánh (v2 chỉ để đối chiếu)
    vague_detector.py        # bộ dò bằng chứng mơ hồ: HIGH → reject, LOW → chỉ log
    stance_reviewer.py       # trọng tài trung lập kiểm tra phe (v1 mặc định: claim; v2: + reasoning; v3: diễn đạt lại → mạnh hơn / yếu đi)
alembic/                     # 0001 tạo 3 bảng, 0002 external_session_id + 1 case file/session,
                             # 0003 vague_evidence + learner_claim, ..., 0008 speeches + turns, 0009 ai_points, 0010 reasoning, 0011 turn wait
scripts/try_case_plan.py     # gọi LLM thật (thủ công, không cần DB)
scripts/try_match.py         # chạy thử cả trận 6 lượt với LLM thật (cần DB dev)
scripts/run_case_plan_batch.py  # batch nhiều motion × 2 phe, ghi JSONL vào experiments/
scripts/compare_case_plan_batches.py  # so sánh v3 vs v4 (nhiều file mỗi phiên bản)
scripts/label_stance.py      # gán nhãn phe MÙ → đo độ chính xác Stance Reviewer
scripts/label_vague_evidence.py  # gán nhãn từng hit vague_evidence → precision detector
scripts/eval_vague_detector.py  # đánh giá bộ dò bằng chứng mơ hồ bằng nhãn tay (tập thiết kế / tập kiểm tra)
scripts/replay_stance_review.py  # chạy lại Stance Reviewer (v1 / v2 / v3) trên lần thử đã gán nhãn hoặc lấy từ batch (LLM thật)
scripts/eval_common.py       # hàm dùng chung cho các script đánh giá
experiments/                 # DỮ LIỆU CHO BÁO CÁO — commit, KHÔNG gitignore
  motions_v1.json            # 10 motion dùng cho batch
  case_plan/                 # kết quả batch: <timestamp>_<prompt_version>.jsonl (+ .summary.json)
  fixtures/                  # bài nói learner viết sẵn cho try_match (match_<motion_id>_<learner_side>.json)
  matches/                   # transcript try_match: <timestamp>_<motion_id>_learner-<side>.json
tests/                       # pytest, Postgres thật + FakeLLMClient
docker/postgres-init/        # SQL tạo DB test khi container khởi tạo lần đầu
docs/AI_DEVELOPMENT_LOG.md
```

## Cài đặt

Python **3.11** (cùng phiên bản với Evaluation service).

```bash
python -m venv venv
venv\Scripts\activate            # macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env             # rồi điền GROQ_API_KEY (hoặc key provider khác)
```

## 1. Chạy PostgreSQL

```bash
docker compose up -d
```

- Container `adpp-ai-generation-postgres`, port host **5433** (không đụng Postgres khác ở 5432).
- Tạo sẵn 2 database: `ai_generation` (dev) và `ai_generation_test` (pytest).
- Nếu volume đã tồn tại từ trước khi có script init, tạo DB test thủ công:
  `docker compose exec postgres psql -U adpp -c "CREATE DATABASE ai_generation_test;"`

## 2. Migrate

```bash
python -m alembic upgrade head
```

Tạo migration mới sau khi sửa model: `python -m alembic revision --autogenerate -m "..."`
(nhớ kiểm tra lại file sinh ra — autogenerate không tự xoá enum type khi downgrade).

## 3. Chạy server

```bash
python -m uvicorn app.main:app --reload --port 8002
# hoặc: python -m app.main   (đọc APP_PORT từ .env)
```

Swagger: http://localhost:8002/docs

Mọi route dùng `external_session_id` (id session bên Main Flow) trong path, không dùng id nội bộ.

| Method | Path | Mô tả |
|---|---|---|
| GET | `/health` | Kiểm tra sống |
| POST | `/opponent/sessions` | Tạo phiên **và** chạy Case Planning đồng bộ. Trả `{opponent_session_id, status}` (không trả case file). Idempotent theo `external_session_id` |
| GET | `/opponent/sessions/{external_session_id}` | Debug: phiên + case file |
| GET | `/opponent/sessions/{external_session_id}/case-plan` | Debug: case file |
| POST | `/opponent/sessions/{external_session_id}/turns` | Sinh bài nói của AI cho 1 lượt (xem **Lượt tranh luận** bên dưới) |

Body `POST /opponent/sessions`: `external_session_id`, `motion`, `learner_side` / `ai_side` (`pro`/`con`,
phải khác nhau), `difficulty` (`easy`=2 luận điểm, `medium`=3, `hard`=3), `language` (hiện chỉ `vi`).

Mã trả về:

| Mã | Khi nào |
|---|---|
| 201 | Tạo mới, case file sẵn sàng |
| 200 | `external_session_id` đã tồn tại với **cùng** dữ liệu (phiên `ready` → không gọi LLM; phiên `failed` → chạy lại Case Planning). Cũng trả 200 nếu request khác đã ghi case file trước (race) |
| 400 | `learner_side == ai_side` |
| 409 | `external_session_id` đã tồn tại nhưng `motion` / `learner_side` / `ai_side` / `difficulty` khác (message nêu trường khác); hoặc phiên đang planning chưa quá `CASE_PLAN_STALE_AFTER_SECONDS` (360s) |
| 422 | Body sai định dạng |
| 502 | LLM lỗi, hoặc output không hợp lệ sau retry |
| 503 | Thiếu API key hoặc sai `LLM_PROVIDER` |
| 504 | Case Planning vượt `CASE_PLAN_TOTAL_BUDGET_SECONDS` (240s); phiên chuyển `failed`, gọi lại để chạy lại |

```bash
curl -X POST http://localhost:8002/opponent/sessions -H "Content-Type: application/json" \
  -d '{"external_session_id": "main-123", "motion": "Học sinh không nên có bài tập về nhà",
       "learner_side": "pro", "ai_side": "con", "difficulty": "medium", "language": "vi"}'
curl http://localhost:8002/opponent/sessions/main-123/case-plan
```

### Lượt tranh luận (Giai đoạn 3a)

Format cố định 6 lượt (`app/opponent/match_format.py`): 1 opening pro · 2 opening con · 3 rebuttal pro ·
4 rebuttal con · 5 closing con · 6 closing pro. Lượt nào của AI suy ra từ `ai_side` của session.

Body: `{"turn_index": <lượt của AI>, "new_learner_speeches": [{"turn_index", "round_type", "text"}]}` — mọi bài nói của
learner **kể từ lượt AI trước** (có thể rỗng, vd AI con lượt 5 ngay sau lượt 4 của chính nó).
Response: `{"turn_index", "round_type", "mode", "speech_text"}`, `mode` ∈ `opening_first` / `opening_reply` /
`rebuttal` / `closing`.

| Mã | Khi nào |
|---|---|
| 201 | Sinh mới |
| 200 | Lượt đã có và bài learner gửi kèm khớp bản đã lưu (không gọi LLM) |
| 400 | `turn_index` không phải lượt của AI; bài learner sai `round_type` / rơi vào lượt AI / nằm sau lượt yêu cầu / gửi trùng |
| 404 | Không có session |
| 409 | Session chưa `ready`; thiếu lượt trước; bài learner khác bản đã lưu; lượt đã có nhưng request khác |
| 422 | Body sai định dạng (vd `text` rỗng) |
| 502 | LLM lỗi; output không hợp lệ sau `TURN_MAX_ATTEMPTS`; hoặc Stance Reviewer vẫn báo lật phe ở lần thử cuối |
| 503 | Thiếu API key |
| 504 | Vượt `TURN_TOTAL_BUDGET_SECONDS` (240s), kể cả khi chỉ vì chờ 429 |

Bộ sinh (`TURN_GENERATOR_VERSION`):
- `turn_full_v3` (**mặc định**) = `turn_full_v2` + "không nhắc lại / diễn giải các quy tắc, chỉ dẫn trong bài nói";
  `turn_full_v2` = `turn_full_v1` + ràng buộc "nói tự nhiên, không đọc thuật ngữ phân tích".
  1 lời gọi JSON `learner_claims → premises → target_premise → ai_points → speech_text`, dùng case file
  (`motion_reading` cố định) + ledger các lượt trước (dựng từ `opponent_turns`), khối ràng buộc ở cuối prompt.
  - Lỗi **cứng** (retry có phản hồi, tối đa `TURN_MAX_ATTEMPTS=3`): JSON / schema, bằng chứng mơ hồ mức HIGH, output
    rỗng / bị cắt (`truncated_max_tokens`). Groq từ chối schema vì output là "mảng tách" hoặc tên trường gõ sai → sửa tất
    định, không gọi lại LLM (`key_repairs.event` = `array_repaired` / `key_repaired`).
  - 429: chờ theo provider, **không giới hạn số vòng**, chỉ bị chặn bởi `TURN_TOTAL_BUDGET_SECONDS=240` (→ 504); tổng
    chờ mỗi lượt ở `opponent_turns.rate_limit_wait_ms`. Lỗi mạng / 5xx thoáng qua: thử lại tối đa
    `LLM_TRANSIENT_RETRIES=2` (cả Case Planning).
  - Độ dài là lỗi **mềm**: prompt yêu cầu 0,8–1,2 × `TURN_TARGET_WORDS_*` (400 / 320 / 260 từ), chấp nhận 0,7–1,25 ×;
    ngoài khoảng → thử lại tối đa 1 lần rồi chấp nhận bản gần nhất (`speech_checks.length_soft_accept`).
  - Chỉ log: bộ dò mức LOW, câu có số ngoài 'Giả sử', xưng "em" (`vague_evidence` / `speech_checks`).
  - `TURN_MAX_TOKENS=6000` (gồm token suy luận); `TURN_REASONING_EFFORT` / `CASE_PLAN_REASONING_EFFORT` = `low` /
    `medium` / `high` (Groq gpt-oss), **mặc định `medium` gửi tường minh** (trận `low` lật phe cả trận). Mỗi lời gọi ghi
    `reasoning_tokens`, `finish_reason`, `reasoning_effort`.
  - **Stance Reviewer cho từng lượt** (v1, model riêng): nhận motion + `ai_points` (P1..Pn) + `speech_text`, không nhận
    phe. Lật phe → sinh lại **trung tính** (không phản hồi), tính vào `TURN_MAX_ATTEMPTS`; hết lượt vẫn lật phe → 502,
    **không bao giờ trả bài nói lật phe**. "Không rõ" / reviewer lỗi → chỉ log.
  - Không có bài learner mới (vd AI con lượt 5) / lượt closing → phân tích (`learner_claims`, `premises`) bị ép rỗng.
- `turn_baseline_v1`: chatbot ngây thơ làm mốc so sánh — **không** dùng case file, **không** Stance Reviewer, lịch sử
  dạng hội thoại, văn bản thuần; cố định 3000 token / 2 lần thử như 3a. `TURN_TEMPERATURE=0.5` dùng chung.

```bash
curl -X POST http://localhost:8002/opponent/sessions/main-123/turns -H "Content-Type: application/json" \
  -d '{"turn_index": 2, "new_learner_speeches": [{"turn_index": 1, "round_type": "opening", "text": "..."}]}'
```

## 4. Chạy test

Cần Postgres đang chạy (bước 1). **Không** cần API key.

```bash
python -m pytest -v
```

- Test dùng Postgres thật (`TEST_DATABASE_URL`), không dùng SQLite (Enum/UUID/JSONB là đặc thù Postgres).
- Đầu phiên: Alembic `downgrade base` → `upgrade head` (kiểm tra luôn migration).
- Mỗi test chạy trong 1 transaction và rollback khi xong.
- LLM được giả lập bằng `FakeLLMClient` (`tests/conftest.py`).

## 5. Thử với LLM thật

```bash
python -m scripts.try_case_plan "Học sinh không nên có bài tập về nhà" --ai-side con --difficulty hard
python -m scripts.try_case_plan "..." --show-prompt     # in cả prompt
```

Không cần DB, không lưu gì — chỉ in case file và log từng lần thử. Tốn token thật.
Cuối output có mục **BANG CHUNG MO HO**: các cụm như "nghiên cứu", "%", "chuyên gia"... tìm thấy
trong case file (chỉ cảnh báo, không reject; có thể báo nhầm — cùng danh sách được lưu vào
`opponent_llm_calls.vague_evidence` khi chạy qua API).

Trên Windows, nếu console báo lỗi encoding khi in tiếng Việt: đặt `PYTHONIOENCODING=utf-8` trước lệnh.

Chạy thử **cả trận** (cần Postgres dev + `python -m alembic upgrade head`; tạo session mới mỗi lần, tốn token thật):

```bash
python -m scripts.try_match --motion-id M01 --learner-side pro                        # TURN_GENERATOR_VERSION
python -m scripts.try_match --motion-id M01 --learner-side con --generator turn_baseline_v1
python -m scripts.try_match --motion-id M01 --learner-side con --generator turn_full_v1 --difficulty hard
python -m scripts.try_match --motion-id M01 --learner-side pro --reasoning-effort low        # so sánh mức suy luận
```

Bài learner lấy từ `experiments/fixtures/match_M01_{pro,con}.json` (viết sẵn, cố định). In transcript + `mode` + số từ
(so với mục tiêu) + latency / token mỗi lượt AI, số lần thử lại + lý do; `turn_full_v1` in thêm `learner_claims`,
`premises`, `target_premise`, `ai_points`. Lượt AI thất bại → in lỗi + từng lần gọi rồi dừng gọn (vẫn ghi file, `completed: false`). Cuối trận in tổng thời
gian chờ 429. Ghi `experiments/matches/<timestamp>_M01_learner-<side>_<generator>[_effort-<x>].json`.

### Stance Reviewer

Sau mỗi case file hợp lệ, một LLM **riêng** (mặc định `groq` / `openai/gpt-oss-20b`, temperature 0) đóng vai
trọng tài trung lập, phân loại từng `claim` + `weighing` là ủng hộ / phản đối kiến nghị / không rõ — **không
được biết phe mong đợi**. Code so với `ai_side`: có mục ngược phe → case file không hợp lệ → retry (tính vào
`CASE_PLAN_MAX_ATTEMPTS`); "không rõ" chỉ cảnh báo. Kết quả lưu ở `opponent_llm_calls.reviewer_verdict` /
`reviewer_detail`. Tắt bằng `STANCE_REVIEW_ENABLED=false` hoặc `--no-review` trong script.

## 6. Batch thử nghiệm (dữ liệu cho báo cáo)

```bash
python -m scripts.run_case_plan_batch                # 10 motion × (pro, con) = 20 lần, độ khó xoay vòng
python -m scripts.run_case_plan_batch --limit 1      # thử nhanh 1 motion × 2 phe
python -m scripts.run_case_plan_batch --prompt-version v3   # chạy prompt v3 (mặc định: CASE_PLAN_PROMPT_VERSION)
python -m scripts.run_case_plan_batch --only-failed experiments/case_plan/<file>.jsonl  # chạy lại cấu hình llm_error

# so sánh 2 batch — chỉ so các cặp cùng (motion, ai_side, difficulty)
python -m scripts.compare_case_plan_batches --v3 experiments/case_plan/<...>_case_plan_v3.jsonl --v4 experiments/case_plan/<...>_case_plan_v4.jsonl
python -m scripts.compare_case_plan_batches --v4 <...>_case_plan_v4.jsonl --v5 <...>_case_plan_v5.jsonl   # đúng 2 nhóm
```

- Đọc motion từ `experiments/motions_v1.json`; mỗi lần chạy ghi **ngay** 1 dòng vào
  `experiments/case_plan/<timestamp>_<prompt_version>.jsonl`: motion, phe, độ khó, prompt_version, model,
  từng lần thử (latency, lỗi, `schema_rejected`, `reviewer_verdict`, `vague_evidence`, raw output), case file
  cuối, trạng thái cuối. Tổng hợp lưu kèm `<cùng tên>.summary.json` và in bảng ra màn hình.
- Gọi LLM thật (tốn token), không dùng DB. `experiments/` là dữ liệu cho báo cáo — **commit**, không gitignore.
- **Rate limit (Groq free tier: 8000 token/phút cho model sinh case):** mặc định nghỉ **35s** giữa các lần chạy
  (`--pause`); gặp 429 thì chờ đúng thời gian Groq yêu cầu + 1–2s. **Chỉ chạy 1 batch tại một thời điểm** — 2 batch
  song song dùng chung hạn mức và hỏng dữ liệu (xem `experiments/case_plan/invalid/README.md`).
- Bảng tổng hợp tách **`content_retries`** (thử lại vì output không hợp lệ — chỉ số chất lượng prompt) và
  **`rate_limit_waits`** (số lần / tổng giây chờ 429 — phản ánh tải, không phải prompt); in token thực tế từng lần
  gọi và `tokens_out` trung bình / lớn nhất so với `CASE_PLAN_MAX_TOKENS`.
- Batch hỏng được chuyển vào `experiments/case_plan/invalid/` (kèm README lý do), không dùng để so sánh.

## 7. Quy trình đánh giá

Ba script chỉ **đọc** JSONL của batch — không gọi LLM, không dùng DB, chạy được khi batch khác đang chạy. Nhãn
lưu ở `experiments/labels/*.csv` (dữ liệu cho báo cáo — commit). Thứ tự dùng:

**Bước 1 — So sánh phiên bản prompt** (sau khi có batch sạch cho cả v3 và v4):

```bash
python -m scripts.compare_case_plan_batches \
    --v3 experiments/case_plan/<a>_case_plan_v3.jsonl experiments/case_plan/<b>_case_plan_v3.jsonl \
    --v4 experiments/case_plan/<c>_case_plan_v4.jsonl
```

- Mỗi phiên bản nhận **nhiều file** (gộp khi chạy lặp); file `--only-failed` (`*_rerun.jsonl`) thay thế lần chạy
  `llm_error` tương ứng của file gốc nếu cả hai cùng được đưa vào.
- **Chỉ so các cấu hình `(motion, ai_side, difficulty)` có ở cả 2 phiên bản**; in danh sách cấu hình bị thiếu.
- Bảng chính: thành công, side_flip, Groq từ chối schema, reject do cụm cấm, `content_retries`,
  `rate_limit_waits`, latency. Bảng `vague_evidence` (case file cuối) **tách nhóm**: `ai_fields` (khẳng định của AI)
  / `learner_claim` (dự đoán lời learner — viện dẫn ở đây hợp lệ) / `unknown` (dữ liệu cũ không có tên trường);
  mỗi nhóm: số case file có hit, tổng hit, hit theo từng cụm.

**Bước 2 — Gán nhãn phe MÙ** (đo độ chính xác của Stance Reviewer):

```bash
python -m scripts.label_stance experiments/case_plan/<v3>.jsonl experiments/case_plan/<v4>.jsonl --n 5 --seed 42 \
    --include "experiments/case_plan/invalid/20260926-171443_case_plan_v3.jsonl:M08:con:easy"
python -m scripts.label_stance --report      # chỉ in đối chiếu từ nhãn đã có
```

- Lấy mẫu từ các **lần thử** case_plan đã được reviewer đánh giá (kể cả lần thử bị reject vì side_flip).
  `--include` thêm đúng lần thử reviewer báo side_flip của lần chạy đó; mẫu được trộn thứ tự theo `--seed`.
- Khi gán **không** hiện phe của AI, độ khó, kết luận hay lý do của reviewer — chỉ kiến nghị, từng luận điểm
  (id + claim + reasoning rút gọn) và weighing. Gõ `u` ủng hộ / `p` phản đối / `k` không rõ cho từng mục, `q` dừng.
- Lưu ngay sau mỗi mẫu vào `experiments/labels/stance_labels.csv`; chạy lại lệnh sẽ bỏ qua mẫu đã gán.
- Gán xong (hoặc `--report`) mới hiện: đồng thuận người vs reviewer theo từng mục + bảng nhầm lẫn 3×3, kết luận
  theo mẫu, các mục người đánh là lật phe (so với phe AI), các mục người và reviewer bất đồng kèm lý do reviewer.

**Bước 3 — Gán nhãn từng hit `vague_evidence`** (precision của detector):

```bash
python -m scripts.label_vague_evidence experiments/case_plan/<file>.jsonl
python -m scripts.label_vague_evidence --report
```

- Mỗi hit hiện cụm từ, tên trường và **câu** chứa cụm. Gõ `a` AI tự viện dẫn mơ hồ (vấn đề thật) / `l` dự đoán
  lời learner (hợp lệ) / `n` bắt nhầm / `s` bỏ qua, `q` dừng. Lưu vào `experiments/labels/vague_evidence_labels.csv`,
  chạy tiếp được.
- Báo cáo: tỷ lệ a / l / n tổng thể, theo nhóm trường, theo cụm; **precision = a / (a + n)** (không tính `l`, bỏ `s`).

**Bước 4 — Đánh giá bộ dò bằng chứng mơ hồ** (sau khi đổi quy tắc trong `app/opponent/vague_detector.py`):

```bash
python -m scripts.eval_vague_detector \
    --design experiments/case_plan/20260927-092737_case_plan_v3.jsonl \
    --test   experiments/case_plan/20260927-094713_case_plan_v4.jsonl
```

- Chạy bộ dò **mới** trên đúng các lần thử mà bộ dò cũ đã quét, đối chiếu với `vague_evidence_labels.csv`.
- **Quy tắc chỉ được thiết kế trên tập `--design`**; tập `--test` để kiểm tra — không chỉnh quy tắc theo kết quả tập test.
- In precision HIGH / LOW cho từng tập, từng hit đúng / nhầm, mục **"chưa có nhãn"** (hit mới mà bộ dò cũ không có —
  gán tay bằng `label_vague_evidence`) và mục **"bỏ sót"** (nhãn `a` không còn hit HIGH nào).

**Bước 5 — Chạy lại Stance Reviewer trên mẫu đã gán nhãn** (so sánh phiên bản reviewer; **gọi LLM thật**):

```bash
python -m scripts.replay_stance_review --reviewer-version v1 --pause 3
python -m scripts.replay_stance_review --reviewer-version v2 --pause 3
python -m scripts.replay_stance_review --reviewer-version v3 --pause 3
python -m scripts.replay_stance_review --compare experiments/reviewer_replay/<a>_stance_review_v1.jsonl \
                                                 experiments/reviewer_replay/<b>_stance_review_v2.jsonl
# lấy mẫu thẳng từ 1 file batch: mọi lần thử bị báo side_flip/unclear + lần thử được chấp nhận ngay sau đó
python -m scripts.replay_stance_review --from-batch experiments/case_plan/<batch>.jsonl --only-flagged \
                                       --reviewer-version v3 --pause 3
```

- `--from-batch`: in cạnh nhau verdict / position lúc chạy batch vs replay theo từng mục, kèm nhãn người (nếu lần thử có
  trong `stance_labels*.csv`), restatement batch + replay (v3) và phản hồi retry generator đã nhận. Ghi
  `experiments/reviewer_replay/<timestamp>_<version>_from-batch.jsonl`. Bỏ `--only-flagged` → mọi lần thử đã được review.

- Nhãn: `experiments/labels/stance_labels.csv` (đợt 1; nếu đã đổi tên → `stance_labels_round1*.csv`) +
  `stance_labels_round2.csv` (đợt 2) + `stance_labels_v5.csv` (đợt 3, batch v5 — motion dạng "A thay vì B"); bỏ qua `*_old.csv`. Lấy đúng các lần thử đã gán nhãn từ JSONL nguồn.
- Reviewer dùng provider / model / `STANCE_REVIEW_MAX_TOKENS` thật (`STANCE_REVIEW_*`), temperature 0, JSON schema;
  429 → chờ theo provider. Ghi cả `tokens_in` / `tokens_out` (file replay cũ trước 2026-09-29 chiều chưa có) và, với v3,
  câu `restatement` của từng mục.
  Mỗi mẫu ghi ngay vào `experiments/reviewer_replay/<timestamp>_<reviewer_version>.jsonl`.
- Bảng: đồng thuận người vs reviewer tách **luận điểm** / **weighing** (weighing đợt 1 không tính — định nghĩa nhãn
  "không rõ" lúc đó chưa rõ), bảng nhầm lẫn 3×3, kết quả riêng 2 ca đặc biệt (M08 con easy lần thử #3 — v1 báo lật phe
  đúng; M10 con medium v4 lần thử #1 — v1 báo sai). `--compare`: không gọi LLM, đặt 2 lần replay cạnh nhau và liệt
  kê mục đổi kết luận.
