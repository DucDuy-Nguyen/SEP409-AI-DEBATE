# AI Development Log — ADPP AI Generation (AI Opponent)

> Tài liệu sống, cùng phong cách với `adpp-ai-service/docs/AI_DEVELOPMENT_LOG.md`.
> Ghi lại: kiến trúc, quyết định thiết kế + lý do, vấn đề đã gặp, việc còn treo.

---

## 1. Kiến trúc hiện tại

- FastAPI + Pydantic v2 + pydantic-settings, port 8002 (Evaluation: 8000).
- PostgreSQL 16 (docker-compose, port host 5433) + SQLAlchemy 2.0 async (asyncpg) + Alembic.
- Python 3.11 — cùng phiên bản với Evaluation service (venv của nó là 3.11.9).
- Module `app/opponent/`: router → service → (prompt, LLM client, ORM). Router không chứa logic.

### 1.1. Năm bảng (migration `0001` → `0012`)

| Bảng | Vai trò |
|---|---|
| `opponent_sessions` | 1 phiên luyện tập với AI: `external_session_id` (TEXT, UNIQUE, id session bên Main Flow, **không FK**), `motion`, `ai_side` + `learner_side` (cùng enum `debate_side`, CHECK `learner_side <> ai_side`), `difficulty`, `language`, `status` (`created/planning/ready/failed` — `created` chỉ còn ở dữ liệu cũ), `motion_type` + `motion_reading_provided` (tuỳ chọn, `0012`, mục 2.13) |
| `opponent_case_files` | Case file (JSONB, validate bằng `CaseFile`) + `prompt_version`, provider, model, temperature. **UNIQUE(session_id)** — mỗi session đúng 1 case file, không phiên bản |
| `opponent_llm_calls` | Log **từng** lần gọi LLM, kể cả lần lỗi/retry: prompt, raw output, lỗi, latency, `purpose` (`case_plan` / `stance_review` / `turn`), `vague_evidence` (JSONB: cụm "bằng chứng mơ hồ" tìm thấy trong case file hợp lệ; NULL = không quét), `reviewer_verdict` (`pass` / `side_flip` / `unclear`) + `reviewer_detail` (JSONB) — kết quả Stance Reviewer cho output của dòng đó, `failure_kind` (loại thất bại, NULL = thành công), `retry_feedback` (phản hồi đã gửi cho lần thử kế tiếp), `tokens_in` / `tokens_out` (usage thực tế), `rate_limit_wait_ms` (thời gian đã chờ sau dòng 429), `key_repairs` (tự sửa tên trường gõ sai, mục 2.4j), `turn_id` (FK → `opponent_turns`, lời gọi sinh bài nói; mục 2.8), `speech_checks` (kiểm tra bài nói chỉ log; mục 2.9), `reasoning_tokens` / `finish_reason` / `reasoning_effort` (mục 2.10) |
| `opponent_speeches` | Snapshot **mọi** bài nói trong trận (learner do Main Flow gửi + AI): `turn_index` (1..6), `round_type`, `speaker` (`learner` / `ai`), `text`. **UNIQUE(session_id, turn_index)** (mục 2.8) |
| `opponent_turns` | Cách sinh 1 bài nói của AI: `speech_id`, `turn_index`, `round_type`, `mode`, `generator_version`, provider, model, temperature, `learner_claims` / `premises` / `target_premise` / `ai_points` (baseline để NULL; `ai_points` từ migration `0009`), `word_count`, `latency_ms`, `tokens_in/out`, `rate_limit_wait_ms` (tổng chờ 429 của lượt, `0011`). **UNIQUE(session_id, turn_index)** |

### 1.2. Luồng tạo phiên (1 bước, đồng bộ)

`POST /opponent/sessions` với `{external_session_id, motion, learner_side, ai_side, difficulty, language}`:

1. `learner_side == ai_side` → 400 (kiểm tra ở service, không ở Pydantic vì Pydantic trả 422).
2. `external_session_id` đã có mà `motion`/`learner_side`/`ai_side`/`difficulty` khác → 409, message nêu
   trường khác (áp dụng cho mọi trạng thái, kể cả `failed`). Trùng khớp và `READY` → 200, trả session cũ,
   **không gọi LLM**.
3. Lấy LLM client (thiếu key → 503, chưa ghi gì vào DB).
4. `INSERT ... ON CONFLICT (external_session_id) DO NOTHING` với status `PLANNING` ngay trong INSERT.
   - Insert được → request này "sở hữu" lần planning, 201.
   - Conflict → `SELECT ... FOR UPDATE` → kiểm tra lại dữ liệu khớp (409 nếu khác); `READY` → 200;
     `PLANNING` chưa quá `CASE_PLAN_STALE_AFTER_SECONDS` → 409; `FAILED` / `PLANNING` kẹt quá ngưỡng →
     chạy lại Case Planning, 200.
5. `generate_case_file()` build prompt theo `CASE_PLAN_PROMPT_VERSION` (mặc định `case_plan_v4`) + JSON
   schema theo độ khó → gọi LLM
   (`asyncio.to_thread`) → `extract_json` → `CaseFile.model_validate` (gồm `example` bắt đầu bằng
   "Giả sử") → **kiểm tra đúng số luận điểm theo độ khó** → `detect_vague_evidence` (chỉ ghi nhận) →
   **cụm bị cấm** (validator, mục 2.4g) → **Stance Reviewer** (LLM riêng, mục 2.4e; lỗi thì gọi lại 1 lần):
   code so phe → `side_flip` là output không hợp lệ.
   Không hợp lệ — kể cả Groq từ chối vì sai schema (400 `json_validate_failed`) và `side_flip` → retry **kèm
   phản hồi nêu rõ trường nào, vi phạm gì** (tối đa `CASE_PLAN_MAX_ATTEMPTS`). 429 → chờ rồi thử lại. Lỗi provider khác → dừng ngay.
   Mọi lời gọi (planner + reviewer) nằm trong `CASE_PLAN_TOTAL_BUDGET_SECONDS`.
6. Ghi mọi attempt vào `opponent_llm_calls`; thành công → case file + `READY`; thất bại → `FAILED`
   (commit cả khi thất bại) → 502.
7. Response chỉ `{opponent_session_id, status}` — không trả case file. Xem case file qua
   `GET /opponent/sessions/{external_session_id}/case-plan` (debug).

---

## 2. Quyết định thiết kế + lý do

### 2.1. Provider abstraction: BẢN SAO CÓ CHỦ ĐÍCH, không import chéo

`app/llm/client.py` copy từ `adpp-ai-service/app/services/llm_client.py`;
`app/llm/json_utils.py` copy hàm `extract_json` từ `adpp-ai-service/app/services/json_utils.py`.
Lý do: 2 service deploy độc lập, không service nào được phụ thuộc code của service kia
(giữ nguyên tắc "AI Debater / AI Evaluator độc lập" ở mục 2.7 dev log Evaluation).
Cái giá: sửa bug ở 1 bên cần cân nhắc sửa bên kia.

Khác biệt so với bản gốc (tối thiểu):
- `generate()` nhận thêm `temperature` / `max_tokens` tuỳ chọn — mỗi tác vụ sinh có tham số
  riêng (`CASE_PLAN_TEMPERATURE`) mà không phải tạo client mới. Không truyền → dùng
  `LLM_TEMPERATURE` / `LLM_MAX_TOKENS` như bản gốc.
- Thêm thuộc tính `provider` / `model` để ghi log DB.
- Default `GROQ_MODEL=openai/gpt-oss-120b` (bản gốc vẫn để `llama-3.3-70b-versatile` trong
  code dù model này đã bị khai tử — mục 3.1 dev log Evaluation; `.env` của Evaluation đã dùng gpt-oss).
- Exception parse đổi tên `EvaluationParseError` → `LLMOutputParseError`; `extract_json` từ chối
  JSON không phải object (vd list).
- Không copy `call_llm_with_retry`: service này cần log từng attempt vào DB nên vòng retry
  nằm trong `opponent/service.py`.
- **Tắt retry ngầm SDK** (`max_retries=0`; Gemini `attempts=1` + thêm timeout) và **bỏ vòng retry
  rate-limit trong `GroqClient`** (chuyển lên service) — xem mục 2.4c.
- `generate()` nhận thêm `json_schema` (structured output strict) — hiện **chỉ `GroqClient` dùng**,
  provider khác bỏ qua và giữ JSON mode cũ. Thêm `schema_rejected_output()` nhận diện 400
  `json_validate_failed` của Groq (xem mục 2.4d).

### 2.2. Temperature Case Planning = 0.7

Evaluation dùng 0.2 (chấm điểm cần ổn định). Sinh case cần đa dạng luận điểm giữa các lần sinh,
nhưng không quá cao để JSON vẫn ổn định. Chưa đo — cần thử bằng `scripts/try_case_plan.py`.
`CASE_PLAN_MAX_TOKENS=4000` vì case file dài hơn kết quả chấm và gpt-oss tính cả token reasoning.

### 2.3. Không bịa dẫn chứng

Kế thừa quyết định "Hướng A" (mục 2.5 dev log Evaluation): prompt cấm bịa số liệu, tên nghiên cứu,
năm, trích dẫn — dẫn chứng chỉ là ví dụ minh hoạ / hiện tượng phổ biến / cơ chế logic.
Với AI đối thủ còn quan trọng hơn: learner học theo cách AI lập luận.

### 2.4. Prompt versioning

Mỗi prompt là 1 file có `PROMPT_VERSION`. **Mặc định `case_plan_v4`**, chọn bằng `CASE_PLAN_PROMPT_VERSION` (`case_plan_v3` vẫn chạy được, dùng để so sánh — mục 2.4g).
`case_plan_v2.py` giữ nguyên để đối chiếu nhưng không còn dùng được với `CaseFile` hiện tại (v2 sinh
`opponent_claim`, đã đổi thành `learner_claim`; v2 không bắt `example` bắt đầu bằng "Giả sử"). Vì vậy
v2 không nằm trong danh sách chọn được. (Trước v4 không có cấu hình chọn version; từ v4 có, vì v3 và v4
dùng chung `CaseFile` nên cả hai đều chạy được.)
**`case_plan_v1` đã bị thay bằng `case_plan_v2` và file v1 đã bị xoá** (v1 sinh `stance`/`evidence`,
không còn khớp `CaseFile`; chưa từng chạy với LLM thật nên không có dữ liệu nào cần đối chiếu).
Giá trị `prompt_version = 'case_plan_v1'` vẫn có thể còn trong DB cũ nếu từng tạo — không ảnh hưởng.
Quy ước từ nay: sửa prompt → tạo `case_plan_v5.py`, không sửa file đang dùng. Version được lưu kèm mỗi case file và mỗi LLM call để so sánh chất lượng
giữa các version về sau.

### 2.4a. Phase 1 chỉnh theo spec (migration `0002`, prompt v2)

- **`external_session_id`** thay id nội bộ trong mọi path: Main Flow chỉ biết id của nó. Không FK vì
  khác hệ thống/DB. Id nội bộ vẫn trả về (`opponent_session_id`) và vẫn là khoá của FK nội bộ.
- **Gộp tạo phiên + Case Planning**, bỏ `POST .../case-plan`: Main Flow gọi 1 lần là có đối thủ sẵn sàng.
- **Idempotent**: Main Flow retry (timeout mạng...) không sinh case file thứ 2 và không tốn token lần 2.
  Race 2 request đồng thời xử lý bằng `ON CONFLICT DO NOTHING` + status `PLANNING` ngay trong INSERT
  (nếu insert `CREATED` rồi mới chuyển `PLANNING`, request thứ 2 có thể chen vào giữa và cũng gọi LLM).
- Quyết định đã được chốt (xem mục 2.4b).
- **LLM client lấy qua factory**, chỉ tạo khi thật sự cần gọi LLM.
- **`CaseFile`**: bỏ `stance` (phe lấy từ session, không để LLM tự mô tả — tránh lệch phe);
  `evidence: list` → `example: str` (ví dụ đời thường hoặc "Giả sử..."), đi cùng quy tắc cấm bịa số liệu.
  Số luận điểm cố định easy=2 / medium=3 / hard=3 (`ARGUMENT_COUNT_BY_DIFFICULTY` trong
  `case_plan_v2.py`, service dùng chung hằng số này); schema chỉ chặn biên 2..3 vì không biết độ khó.
- Prompt v2 chứa **nguyên văn** 4 câu của spec (khoá phe, cấm bịa số liệu, bối cảnh Việt Nam,
  tiếng Việt + chỉ JSON); có test kiểm tra từng câu.
- Migration `0002` có backfill cho dữ liệu cũ: `external_session_id = id::text`,
  `learner_side` = phe đối diện `ai_side`, case file trùng session giữ bản mới nhất. Đã thử
  downgrade → chèn dữ liệu kiểu cũ → upgrade trên DB dev.

### 2.4b. Quyết định đã chốt với Khoa (2026-09-25)

1. **Phiên `failed` được chạy lại** khi gọi lại `POST /opponent/sessions` cùng `external_session_id`
   (và cùng dữ liệu). Lý do: đã bỏ endpoint `case-plan`, không chạy lại thì phiên lỗi kẹt vĩnh viễn.
   Không vi phạm "1 case file / session" vì phiên failed chưa có case file.
2. **`language` chỉ nhận `"vi"`** (khác → 422): prompt v2 bắt buộc tiếng Việt, nhận `"en"` mà trả tiếng
   Việt là hợp đồng API sai. Mở rộng cần prompt mới. Cột `language` trong DB giữ nguyên.
3. **Phiên `ready` không cần API key**: LLM client chỉ tạo (qua factory) khi thật sự phải gọi LLM, nên
   gọi lại phiên đã sẵn sàng vẫn trả 200 kể cả khi server thiếu key / sai provider.
4. **Gọi lại cùng `external_session_id` nhưng khác dữ liệu → 409** (thay cho quyết định cũ "bỏ qua dữ
   liệu mới"). So sánh 4 trường `motion` (sau strip), `learner_side`, `ai_side`, `difficulty`; message nêu
   rõ trường nào khác. Kiểm tra trước cả trạng thái — phiên `failed` khác dữ liệu cũng 409, không chạy lại
   với dữ liệu mới. Trùng khớp → hành vi cũ (200).

### 2.4c. Giới hạn thời gian planning + ngưỡng "kẹt" — ĐÃ XỬ LÝ (2026-09-25)

**Trước (đã bỏ):** ngưỡng kẹt 900s, validator theo công thức `LLM_TIMEOUT × 3 × attempts + 120s`
(× 3 vì SDK tự retry ngầm 2 lần). Vẫn có 2 lỗ hổng: vòng retry rate-limit của `GroqClient` không bị chặn
thời gian nên có thể vượt ngưỡng, và khi đó request chạy lại planning sẽ bị 500 lúc commit case file.

**Bây giờ:**

1. **Tắt retry ngầm của SDK.** OpenAI / Anthropic / Groq khởi tạo với `max_retries=0`; Gemini đặt rõ
   `retry_options.attempts=1` (SDK `google-genai` mặc định đã không retry, đặt rõ để không phụ thuộc
   mặc định) và thêm timeout (bản copy trước đó không có timeout cho Gemini → thread có thể treo vô hạn).
   Mỗi `generate()` = đúng 1 HTTP request.
2. **Retry rate-limit chuyển từ `GroqClient` lên service** (`_attempt_loop`), áp dụng cho mọi provider
   (nhận diện 429 qua `status_code` / `code`): tối đa `CASE_PLAN_RATE_LIMIT_RETRIES` (4) lần, chờ
   `CASE_PLAN_RATE_LIMIT_WAIT_SECONDS` (3s) — cùng 5 lần gọi / 3s như bản gốc. Không tính vào
   `CASE_PLAN_MAX_ATTEMPTS` (chỉ đếm output không hợp lệ). **Mọi lần gọi LLM, kể cả 429, đều là 1 dòng
   `opponent_llm_calls`.**
3. **`CASE_PLAN_TOTAL_BUDGET_SECONDS` (mặc định 240s)**: `asyncio.wait_for` bọc toàn bộ vòng thử (mọi
   lần gọi LLM + mọi lần chờ rate-limit). Hết budget → phiên `FAILED`, HTTP **504**, ghi 1 dòng
   `opponent_llm_calls` với `error` bắt đầu bằng `budget_exceeded` (lần gọi đang dở; hoặc dòng không có
   raw output nếu hết budget lúc đang chờ retry rate-limit — ghi rõ "chua goi LLM").
   **Giới hạn đã biết:** `asyncio.to_thread` không huỷ được thread — lần gọi HTTP đang dở vẫn chạy tiếp
   tới khi xong/timeout (tối đa `LLM_TIMEOUT_SECONDS`, vì đã tắt retry SDK) và kết quả bị bỏ; có thể vẫn
   tốn token. Budget đảm bảo thời gian **phản hồi request**, không đảm bảo huỷ hẳn lời gọi.
4. **Ngưỡng kẹt:** `CASE_PLAN_STALE_AFTER_SECONDS` mặc định **360s**. Validator lúc khởi động:
   `CASE_PLAN_STALE_AFTER_SECONDS > CASE_PLAN_TOTAL_BUDGET_SECONDS + 60`, sai → không khởi động. Bỏ
   công thức theo LLM timeout: budget đã chặn cứng thời gian planning nên không cần suy ra từ timeout.
5. **IntegrityError UNIQUE(session_id) khi ghi case file** (request khác đã ghi trước — vd chạy lại phiên
   bị coi là kẹt trong khi lần đầu vẫn sống): rollback, ghi lại log `opponent_llm_calls` của request này
   (bị rollback cùng case file), đọc lại session và trả **200** với session + case file đã có. Case file
   vừa sinh bị bỏ. Chỉ bắt đúng constraint `uq_opponent_case_files_session_id`, IntegrityError khác vẫn nổi lên.

**Ảnh hưởng tới Evaluation service (CHỈ GHI CHÚ, không sửa bên đó):** `adpp-ai-service/app/services/llm_client.py`
vẫn dùng mặc định SDK (`max_retries=2` cho OpenAI / Anthropic / Groq) và vòng retry rate-limit 5 lần trong
`GroqClient` — retry ngầm, không log, một lần `generate()` có thể kéo dài nhiều lần `LLM_TIMEOUT_SECONDS`.
Bản copy ở đây giờ **khác bản gốc về hành vi retry** (xem mục 2.1).

### 2.4d. Case Planning v2 → v3 (2026-09-26)

**Nguồn:** 3 mẫu Khoa chạy thật với prompt v2 (Groq, `openai/gpt-oss-120b`, temperature 0.7), lưu
nguyên văn tại [`docs/samples/case_plan_v2_real_runs.md`](samples/case_plan_v2_real_runs.md):

| Mẫu | Motion | Phe AI / độ khó |
|---|---|---|
| 1 | Nên cấm học sinh sử dụng điện thoại trong trường học | Phản đối / easy |
| 2 | Nên bỏ kỳ thi tốt nghiệp THPT | Đề xuất / medium |
| 3 | Mạng xã hội gây hại nhiều hơn có lợi cho giới trẻ | Phản đối / hard |

**Lỗi quan sát được (Khoa) → thay đổi v3:**

| Lỗi v2 (bằng chứng nguyên văn) | Mẫu | Thay đổi v3 |
|---|---|---|
| Phe Phản đối thêm ngoại lệ làm hẹp kiến nghị: *"…trừ những trường hợp đặc biệt được giáo viên cho phép"*; định nghĩa "điện thoại" đóng khung có lợi (*"…và hỗ trợ học tập"*) | 1 | Luật phe Phản đối: chấp nhận cách hiểu phổ biến, không thêm ngoại lệ |
| Phe Đề xuất cài strawman vào định nghĩa, sai thực tế VN: kỳ thi *"là tiêu chuẩn duy nhất để xét tuyển vào đại học"* (thực tế còn xét học bạ, đánh giá năng lực…) | 2 | Luật phe Đề xuất: định nghĩa công bằng như trọng tài trung lập, không mô tả sai hiện trạng, không chắc thì đừng nêu |
| Mâu thuẫn nội tại: A1 (xem video học tập trên lớp) tấn công đúng trường hợp mà `motion_interpretation` đã miễn trừ | 1 | Tự kiểm tra: không lập luận nào dựa vào điều phần định nghĩa đã loại trừ |
| Bằng chứng mơ hồ: *"nhiều quốc gia đã áp dụng mô hình này thành công"* (O2), *"các giải pháp thay thế đã được chứng minh khả thi"* (weighing) | 2 | Cấm 4 cụm mơ hồ trong prompt + `detect_vague_evidence` ghi log |
| Ví dụ đọc như sự kiện thật: A2 *"Một trường trung học ở Hà Nội quyết định…"* | 2 | Mọi ví dụ PHẢI bắt đầu bằng "Giả sử" + validator (sai → retry) + `pattern` trong JSON schema |
| Impact thổi phồng: *"giảm tỷ lệ lo âu, trầm cảm"* (mẫu 2 A1); *"giảm tỷ lệ trầm cảm và tự tử"* (mẫu 3 A2); *"giảm tỷ lệ thất nghiệp và nạn di cư lao động"* (mẫu 3 A3) | 2, 3 | Impact phải tương xứng với reasoning |
| Lọt tiếng Anh: *"phe phản đối (Opposition) thắng"* — nhãn `PHẢN ĐỐI (Opposition)` của prompt v2 lọt vào output | 1 | Chỉ tiếng Việt, kể cả tên phe (Đề xuất / Phản đối); bỏ nhãn tiếng Anh + "MOTION" khỏi prompt |
| Gõ sai tên trường: `"motion_interinterpretation"` → lần 1 lỗi validation, retry OK | 2 | Bật structured output (JSON schema strict) trên Groq |
| (Không phải lỗi v2) `opponent_claim` dễ nhầm: trong module "opponent", "opponent" = AI, nhưng field là luận điểm của **người học** | — | Đổi thành `learner_claim` |

**Lỗi Khoa ghi nhận nhưng v3 CHƯA nhắm tới:** O1 và O3 dùng lặp cùng một chiến lược phản bác ("do lạm
dụng / thiếu hướng dẫn") — mẫu 3; bối cảnh Việt Nam chung chung / bề mặt (chỉ thêm tên thành phố) — mẫu 1,
3 (v3 giữ nguyên câu "Ưu tiên bối cảnh Việt Nam…" của v2, không thêm gì).

**Các lớp kiểm tra bằng code của v3 bắt được gì trên chính 3 output v2** (chạy lại validator / detector /
schema v3 trên JSON đã lưu, sau khi đổi `opponent_claim` → `learner_claim` như migration `0003`):

| Mẫu | Validator v3 | `detect_vague_evidence` | Ghi chú |
|---|---|---|---|
| 1 | Hợp lệ | `[]` | "(Opposition)" không có lớp code nào bắt — chỉ dựa vào prompt |
| 2 | **Từ chối** — `arguments.1.example` không bắt đầu bằng "Giả sử" | `["nhiều quốc gia", "chứng minh"]` — đúng và đủ 2 cụm Khoa ghi nhận, không báo nhầm | Lần thử 1 (`motion_interinterpretation`) bị schema strict chặn (`additionalProperties: false` + `required`) |
| 3 | Hợp lệ | `[]` | Mọi lỗi (impact, lặp chiến lược phản bác) chỉ dựa vào prompt |

→ Lỗi của mẫu 1 và 3 **chỉ sửa được bằng prompt**; muốn biết v3 có hiệu quả phải chạy lại. Các câu thật
của mẫu 2 đã thành test hồi quy (`tests/test_case_plan_unit.py`, `test_real_v2_sample2_*`).

**Chạy lại v3 trên đúng 3 cấu hình** (Claude, 2026-09-26, mỗi cấu hình **n=1**, temperature 0.7 — khác
biệt có thể một phần do ngẫu nhiên khi sinh; đánh giá "đã sửa / chưa" là nhận xét của Claude khi đọc,
chưa qua Khoa). Nguyên văn: [`docs/samples/case_plan_v3_rerun.md`](samples/case_plan_v3_rerun.md). Cả 3
thành công ở lần thử 1, đúng phe, 3/3 ví dụ mỗi mẫu bắt đầu bằng "Giả sử".

| Lỗi v2 | Mẫu | v3 | Nhận xét |
|---|---|---|---|
| Ngoại lệ làm hẹp kiến nghị + mâu thuẫn nội tại | 1 | **Đã sửa** | *"cấm hoàn toàn … bao gồm cả việc gọi, nhắn tin và truy cập internet"* — không còn ngoại lệ, nên không còn chỗ để mâu thuẫn |
| Định nghĩa thiên vị | 1, 2 | **Đã sửa** | "điện thoại di động" định nghĩa trung tính; kỳ thi THPT giờ là *"một trong các tiêu chí xét tuyển đại học"* (đúng thực tế) |
| Lọt tiếng Anh | 1 | **Đã sửa** | *"phe phản đối có lập luận mạnh hơn"* — không còn "(Opposition)" |
| Ví dụ không có "Giả sử" | 2 | **Đã sửa** | Ép bằng schema + validator, không phụ thuộc prompt |
| Bằng chứng mơ hồ | 2 | **CHƯA sửa** | O2: *"nhiều quốc gia đã áp dụng mô hình này mà vẫn duy trì tiêu chuẩn tuyển sinh cao"* — gần như nguyên câu v2, **dù v3 cấm đích danh**. `detect_vague_evidence` bắt được (`["nhiều quốc gia"]`). "đã được chứng minh" thì hết |
| Impact thổi phồng | 1, 2, 3 | **Sửa một phần** | Nhẹ hơn (mẫu 3: *"giảm nguy cơ trầm cảm"* thay cho *"giảm tỷ lệ trầm cảm và tự tử"*) nhưng vẫn còn bước nhảy: mẫu 1 A1 *"…thậm chí tử vong"*; mẫu 2 A1 *"giảm tỷ lệ bỏ học"*, A3 đánh giá theo tiêu chuẩn địa phương → *"tăng cơ hội … tiếp cận đại học"*; mẫu 3 A3 *"xây dựng cộng đồng bền vững và dân chủ"* |
| Lặp chiến lược phản bác (v3 không nhắm tới) | 1, 3 | **Vẫn còn** | Mẫu 3: O1 *"cách sử dụng không kiểm soát"* / O3 *"vấn đề quản lý thời gian"*; mẫu 1: O1, O2 cùng *"thay vì cấm, đặt quy tắc + giáo dục + giám sát"* |
| Bối cảnh VN bề mặt (v3 không nhắm tới) | 1, 3 | **Gần như không đổi** | Mẫu 1 không có chi tiết VN nào; mẫu 3 thêm Zalo, "tỉnh miền núi". Mẫu 2 khá hơn (A3 bất bình đẳng vùng miền là vấn đề VN thật) |

**Motion mất dấu trong PowerShell (Khoa hỏi):** 3 mẫu v2 chạy qua script → **không có trong DB**, không
kiểm tra được cột `motion`. Kiểm tra trực tiếp: gọi Python từ PowerShell 5.1 (console UTF-8) với tham số
"Nên cấm học sinh" → `sys.argv` nhận **đúng từng ký tự**. Dạng hiển thị "xã→xa", "hơn→hon", "ạ→?" giống
chuyển mã OEM (cp437) kiểu best-fit — không xác định được lỗi chỉ ở dòng lệnh hiển thị hay đã làm hỏng
tham số ở máy Khoa (output v2 có motion đúng dấu, nhưng model có thể tự suy ra từ chữ không dấu). Đã sửa
script: in lại motion **đã nhận** (kèm dạng `ascii()` đọc được cả khi console hiển thị sai) + cảnh báo nếu
có `?` / U+FFFD; bỏ việc cắt raw output ở 2000 ký tự (mẫu 2 lần 1 bị cắt). 3 lần chạy lại v3 ở trên xác nhận
motion tới model nguyên vẹn. Qua API (Main Flow gửi JSON UTF-8) không đi qua console nên không bị ảnh hưởng.

**Code đi kèm:**
- `CaseArgument.example`: validator bắt đầu bằng "Giả sử" (chuẩn hoá NFC trước khi so — tiếng Việt dạng
  tổ hợp NFD nhìn giống nhưng khác byte). Sai → `ValidationError` → retry như output sai định dạng.
- `detect_vague_evidence(case_file)`: quét **mọi** text trong case file (không phân biệt hoa thường) tìm
  "nghiên cứu", "thống kê", "%", "nhiều quốc gia", "nhiều nước", "chứng minh", "chuyên gia", "theo báo
  cáo". **Không reject** — lưu danh sách vào `opponent_llm_calls.vague_evidence` (migration `0003`) và in
  trong script. Lý do không reject: nhiều cụm có cách dùng hợp lệ (xem quan sát bên dưới), dùng để đo tần
  suất vi phạm quy tắc 3 trên dữ liệu thật trước khi quyết định có chặn hay không.
- Migration `0003`: thêm cột `vague_evidence`; đổi key `opponent_claim` → `learner_claim` trong JSONB các
  case file cũ (downgrade đổi ngược). `GET .../case-plan` giờ trả `content` là JSON thô như đã lưu, không
  validate lại bằng `CaseFile` hiện tại — nếu không, case file cũ (example không có "Giả sử") làm GET lỗi 500.

**Structured output (JSON schema) — ĐÃ BẬT cho Groq:**
- Kiểm chứng 2026-09-26 với `openai/gpt-oss-120b`: API chấp nhận `response_format = json_schema` với
  `strict: true`, kể cả `$defs`/`$ref`, `minItems`/`maxItems`, `pattern` có dấu tiếng Việt.
- Schema sinh **từ `CaseFile`** (`case_plan_v3.build_response_schema`) để không lệch validator; strict
  mode yêu cầu mọi object `additionalProperties: false` + mọi field `required`. Ép thêm: số luận điểm
  đúng theo độ khó, `example` khớp `^Giả sử`. Validator Pydantic vẫn chạy sau — schema chỉ là lớp chặn sớm.
- **Phát hiện quan trọng:** strict mode của Groq **không** ép lúc sinh (constrained decoding). Model sinh
  xong, Groq mới kiểm tra; sai → **HTTP 400 `json_validate_failed`** kèm output bị từ chối trong
  `failed_generation`. Nếu coi đây là lỗi provider (như code ban đầu) thì bật schema **làm mất lượt retry**
  → đã xử lý: 400 `json_validate_failed` được coi là output không hợp lệ (retry kèm câu nhắc,
  `failed_generation` lưu vào `raw_output`).
- Provider khác (OpenAI / Anthropic / Gemini) chưa bật dù có hỗ trợ dạng tương tự — ngoài phạm vi, bật
  khi đổi provider. Tắt toàn bộ bằng `CASE_PLAN_USE_JSON_SCHEMA=false` nếu model mới không hỗ trợ.

**Quan sát khi kiểm chứng v3 (Claude chạy thật 4 lần, 2026-09-26, motion "Nên cấm học sinh dùng điện
thoại trong trường học" — n rất nhỏ, chỉ để kiểm tra tích hợp, KHÔNG phải đánh giá chất lượng):**

| # | Phe AI / độ khó | Kết quả |
|---|---|---|
| 1 | Đề xuất / medium | Thành công lần 1. Đúng phe, 3 ví dụ đều "Giả sử", không cụm mơ hồ. Ví dụ A1 có số giả định ("30 học sinh… 3 tin nhắn mỗi giờ") — hợp lệ theo luật vì nằm trong "Giả sử", nhưng sát ranh giới |
| 2 | Phản đối / easy | Lần 1 bị Groq từ chối (400 `json_validate_failed`: 1 luận điểm trả về dạng chuỗi thay vì object). Lúc đó code chưa xử lý → dừng. **Output bị từ chối lập luận ỦNG HỘ lệnh cấm dù AI là phe Phản đối** (lật phe) |
| 3 | Phản đối / easy | Thành công lần 1 (sau khi sửa xử lý 400). Đúng phe |
| 4 | Phản đối / easy | Thành công lần 1. Đúng phe. `vague_evidence = ["chứng minh"]` — **cảnh báo nhầm**: "phe phản đối thắng khi chứng minh rằng…" trong weighing là cách dùng hợp lệ |

### 2.4e. Stance Reviewer (đưa lên sớm từ Phase 3, 2026-09-26)

**Vì sao:** đã thấy AI **lật phe** — output bị Groq từ chối ở lần kiểm chứng v3 (mục 2.4d, phe Phản đối
nhưng lập luận ỦNG HỘ lệnh cấm). Prompt đã khoá phe ("Phe của bạn là CỐ ĐỊNH…") nhưng không chặn được hoàn
toàn, và không có lớp code nào phát hiện được. Lật phe là lỗi nặng nhất với AI đối thủ (learner tranh luận
với một đối thủ đồng ý với mình), nên cần kiểm tra độc lập.

**Thiết kế** (`app/opponent/stance_reviewer.py`, thuần — không gọi LLM, không DB — để Phase 3 dùng lại
cho từng lượt nói):
- **LLM riêng, cấu hình được**: `STANCE_REVIEW_PROVIDER` / `STANCE_REVIEW_MODEL` (mặc định `groq` /
  `openai/gpt-oss-20b` — đã kiểm chứng có trên Groq, nhận JSON schema strict, temperature 0;
  `llama-3.1-8b-instant` không còn trên Groq). Temperature **cố định 0** trong code. Độc lập với
  `LLM_PROVIDER` (đổi planner sang OpenAI thì reviewer vẫn chạy Groq, trừ khi đổi cả biến reviewer).
- **Trọng tài trung lập, ngôi thứ ba**: system prompt "TRỌNG TÀI TRUNG LẬP… KHÔNG phải người tranh biện";
  user prompt "Một đội tranh luận đưa ra các luận điểm sau về kiến nghị '{motion}'". Nhắc đánh giá theo
  **hướng tác động lên kiến nghị**, không theo từ bề mặt ("X gây hại" với kiến nghị "Nên cấm X" là ủng hộ).
- **Input chỉ gồm motion + `claim` từng argument + `weighing`** — không reasoning / example / impact /
  luận điểm dự đoán của learner. **Không cho biết phe mong đợi**: `build_review_prompt()` không có tham số
  phe; test kiểm tra cùng case file với ai_side = pro và con cho ra prompt reviewer **giống hệt nhau**.
- **LLM chỉ phân loại**, mỗi mục `ung_ho_kien_nghi` / `phan_doi_kien_nghi` / `khong_ro` + lý do; JSON
  schema strict ép đúng số mục, id trong danh sách, position trong 3 giá trị.
- **Code kết luận** (`judge()`), không để LLM quyết: có mục **ngược** phe → `side_flip` → case file không
  hợp lệ → retry Case Planning (**tính vào `CASE_PLAN_MAX_ATTEMPTS`**), câu nhắc nêu đúng id bị lật và phe
  phải bảo vệ. Không ngược phe nhưng có `khong_ro` → `unclear`: log cảnh báo, **không reject**.
- **Reviewer lỗi** (gọi thất bại / output sai / thiếu id) → coi như `unclear`, ghi `reviewer_error` — **tự
  quyết, spec không nói**: reviewer là lớp bảo vệ thêm, không để nó làm hỏng Case Planning khi Groq trục trặc.
  Hệ quả: nếu reviewer lỗi, lật phe có thể lọt qua (có log để đo).
- **Log**: lời gọi reviewer là 1 dòng `opponent_llm_calls` riêng (`purpose=stance_review`, model /
  prompt_version `stance_review_v1` / temperature 0 riêng). Kết luận lưu ở `reviewer_verdict` +
  `reviewer_detail` (position từng mục, `flipped_ids`, `unclear_ids`) trên **cả dòng case_plan được review**
  và dòng stance_review. `attempt` đánh số liên tục qua mọi lời gọi của 1 lần planning.
- **Budget**: lời gọi reviewer (và chờ 429 của nó) nằm trong `CASE_PLAN_TOTAL_BUDGET_SECONDS`; hết budget
  giữa lúc review → dòng bị cắt ghi `purpose=stance_review`, case plan đang chờ review ghi `budget_exceeded`.
  Retry 429 dùng chung bộ đếm cho planner + reviewer.
- **Chi phí**: thêm ~1 lời gọi model nhỏ (~2s thực đo) mỗi lần thử Case Planning.
- Migration `0004`: `llm_call_purpose` += `stance_review`; enum `reviewer_verdict`; cột `reviewer_verdict`,
  `reviewer_detail` (đây là các cột đã dự kiến cho Phase 3, làm luôn bây giờ).
- Test: API test từng **gọi reviewer thật trên Groq** vì chưa override dependency mới (lần chạy đầu sau khi
  thêm reviewer) → đã thêm `FakeStanceReviewer` vào fixture **và** xoá API key thật khỏi môi trường test
  trong `conftest.py`, để lỗi tương tự sau này thất bại ngay thay vì tốn token.

**Kiểm chứng thật** (batch `--limit 1`, motion M01 × 2 phe): reviewer phân loại đúng cả 2 lần (pro: mọi mục
`ung_ho_kien_nghi`; con: mọi mục `phan_doi_kien_nghi`), lý do hợp lý, ~1.8–2.1s/lần.

### 2.4f. Batch runner (`scripts/run_case_plan_batch.py`)

- `experiments/motions_v1.json`: 10 motion bối cảnh VN. Mỗi motion × (pro, con) = 20 lần; độ khó xoay vòng
  easy → medium → hard theo thứ tự lần chạy (mỗi motion có 2 độ khó khác nhau cho 2 phe).
- Ghi **ngay từng dòng** JSONL vào `experiments/case_plan/<timestamp>_<prompt_version>.jsonl` (dừng giữa
  chừng vẫn còn dữ liệu), kèm `.summary.json`. Mỗi dòng: motion, phe, độ khó, prompt_version, model,
  reviewer_model, trạng thái cuối, từng lần thử (purpose, latency, lỗi, `schema_rejected`, `reviewer_verdict`,
  `reviewer_detail`, `vague_evidence`, raw output), case file cuối.
- Bảng tổng hợp: thành công, số lần `side_flip` bị bắt, số lần Groq từ chối schema, số case file có
  `vague_evidence`, `unclear`, latency trung bình.
- `--pause` (mặc định 5s) giữa các lần để giảm 429 trên free tier. Không dùng DB (gọi `generate_case_file`).
- `experiments/` là dữ liệu cho báo cáo — commit, **không** gitignore.

### 2.4g. Retry có phản hồi, cụm bị cấm thành validator, prompt v4 (2026-09-26)

**1. Retry có phản hồi cho MỌI lỗi.** Trước đây chỉ `side_flip` có câu nhắc cụ thể; lỗi khác dùng câu
chung chung "CHỈ trả về JSON hợp lệ…" → model không biết sửa gì. Giờ mọi output không hợp lệ đều sinh phản
hồi `[PHẢN HỒI LẦN THỬ TRƯỚC] Output trước của bạn KHÔNG hợp lệ vì: - …` nêu **trường nào, vi phạm gì**:

| `failure_kind` | Phản hồi (ví dụ) |
|---|---|
| `invalid_json` | Output không phải một JSON object hợp lệ (bị cắt / có text thừa) |
| `schema_validation` | `` `arguments[0].example`: example phai bat dau bang 'Giả sử' ``; `` `motion_interpretation`: thiếu trường bắt buộc `` + `` `motion_interinterpretation`: trường không có trong cấu trúc mẫu (có phải ý bạn là `motion_interpretation`?) `` (gợi ý tên đúng bằng `difflib` — lỗi thật của mẫu v2 số 2) |
| `argument_count` | `` `arguments`: độ khó này cần ĐÚNG 3 luận điểm, bạn trả về 2 `` |
| `banned_phrase` | `` `anticipated_opponent_arguments[1].planned_response` chứa lời viện dẫn bị cấm "…" — bỏ đi, thay bằng lập luận dựa trên cơ chế `` |
| `schema_rejected` | Output bị nhà cung cấp từ chối vì không khớp JSON schema (chi tiết `jsonschema:` trích từ lỗi Groq, vd `'/arguments/1' … expected object, but got string`) |
| `side_flip` | ~~Trọng tài đánh giá luận điểm A2 ("…claim…") đang bảo vệ phe người học; mọi luận điểm PHẢI bảo vệ phe …~~ — từ mục 2.4m: KHÔNG phản hồi, retry trung tính (prompt gốc) |

- Phản hồi gắn vào **prompt gốc** (không cộng dồn qua các lần thử — lần 3 chỉ mang phản hồi của lần 2).
- **Log**: phản hồi lưu ở `opponent_llm_calls.retry_feedback` trên **dòng bị lỗi** sinh ra nó (NULL nếu hết
  lượt, không retry), cùng `failure_kind` (migration `0005`). Batch JSONL cũng ghi 2 trường này.
- Không thay đổi: lỗi provider khác → dừng ngay; 429 → chờ, không phản hồi (không phải lỗi output).

**2. 4 cụm bị cấm → validator** (`find_banned_phrases`, `BANNED_EVIDENCE_PATTERNS`): output chứa → không
hợp lệ (`banned_phrase`) → retry có phản hồi. Áp dụng cho **cả v3 và v4** (v4 bỏ danh sách khỏi prompt nhưng
vẫn chặn bằng code) để so sánh công bằng. Cụm rộng (`VAGUE_EVIDENCE_PHRASES`: "chứng minh", "%"…) **vẫn chỉ
log** vì hay báo nhầm (mục 2.4d). **Tự quyết:** mẫu của "nhiều quốc gia đã áp dụng thành công" là **"nhiều quốc
gia đã áp dụng"** (bỏ "thành công") — output thật của v3 viết "nhiều quốc gia đã áp dụng mô hình này mà vẫn…",
khớp nguyên văn sẽ lọt đúng câu vi phạm duy nhất đã thấy. 3 cụm còn lại khớp nguyên văn.

**Cập nhật — phạm vi quét (2026-09-26):** validator cụm cấm **chỉ quét khẳng định của AI**: `motion_interpretation`,
`definitions[*]` (term, meaning), `arguments[*].claim/reasoning/example/impact`,
`anticipated_opponent_arguments[*].planned_response`, `weighing`. **Không quét `learner_claim`** — đó là dự đoán
điều learner sẽ nói, không phải AI tự viện dẫn. Bằng chứng: batch v3 lúc 17:14, M10 "Nên đánh thuế cao đối với
đồ uống có đường" / con / medium bị reject **oan** vì O3 `learner_claim` = *"Nhiều quốc gia đã áp dụng thuế cao
đối với đồ uống có đường và đạt được thành công…"* — một dự đoán hợp lý (và `planned_response` phản bác đúng
hướng: thành công ở nơi khác đi kèm chính sách hỗ trợ, không sao chép thẳng vào VN được); lần retry sau đó bị 429
nên cả lần chạy thành `llm_error`. Đã thành test hồi quy (`test_regression_m10_con_medium_*`). `title` / `id`
cũng không quét (spec chỉ liệt kê các trường trên). (**Cập nhật sau:** `title` cũng được quét — title cũng là khẳng định của AI; chỉ bỏ các trường `id`.)
`detect_vague_evidence` (chỉ log) **vẫn quét mọi trường**
nhưng giờ ghi kèm tên trường: `vague_evidence = [{"phrase", "field"}]` (dòng DB / JSONL cũ là list chuỗi).

**3. Prompt v4** (`case_plan_v4.py`): **chỉ khác v3 đúng quy tắc 3** (có test so từng dòng) — thay danh sách
cụm cấm bằng hướng dẫn tích cực: "Khi đề xuất giải pháp thay thế hoặc khẳng định một điều khả thi, hãy lập
luận dựa trên cơ chế hoạt động của nó, không dựa trên việc nơi khác đã áp dụng hay đã được chứng minh."
Lý do: chạy lại v3 vẫn thấy "nhiều quốc gia đã áp dụng…" dù bị cấm đích danh — liệt kê cụm cấm không đủ, và
có thể còn gợi ý chính cụm đó. Giả thuyết: nói model **làm gì** (lập luận bằng cơ chế) hiệu quả hơn nói **không
làm gì**. **Chưa kiểm chứng** — cần batch v3 vs v4 (mục 6). v4 dùng chung với v3: `CaseFile`, số luận điểm,
nhãn phe, luật theo phe, mẫu JSON, JSON schema (import từ v3). `CASE_PLAN_PROMPT_VERSION` (mặc định
`case_plan_v4`), Settings chỉ nhận `case_plan_v3` / `case_plan_v4`.

**4. Batch + so sánh:** `run_case_plan_batch.py --prompt-version v3|v4` (tên file output đã có
prompt_version); bảng tổng hợp thêm "bị reject do cụm cấm" và "số lần retry trung bình" (retry = số lần gọi
case_plan vượt lần đầu, **không tính lần bị 429**). `compare_case_plan_batches.py A.jsonl B.jsonl`: chỉ so các
cặp cùng `(motion, ai_side, difficulty)` (lần chạy chỉ có ở 1 file bị bỏ, in số lượng; trùng khoá → lấy lần
đầu + cảnh báo), bảng: tỷ lệ thành công, side_flip, Groq từ chối schema, có `vague_evidence`, bị reject do cụm
cấm, retry trung bình, latency trung bình, cột chênh lệch B − A. Đọc được file JSONL cũ (thiếu `failure_kind`).

**5. Stance Reviewer thử lại 1 lần khi lỗi** (`stance_reviewer.MAX_CALLS = 2`): gọi thất bại hoặc output sai
→ gọi lại reviewer 1 lần, **không** tính là một lần thử Case Planning; vẫn lỗi → `unclear`, chấp nhận như trước.
Cả 2 lần gọi đều là dòng log riêng; `reviewer_detail.reviewer_calls` ghi số lần đã gọi. `side_flip` là kết
luận hợp lệ, không phải lỗi → không gọi lại reviewer mà retry Case Planning. Giới hạn: temperature 0 + cùng
prompt → output **sai** có thể lặp y hệt; lần gọi lại chủ yếu cứu lỗi tạm thời (mạng, 5xx, schema ngẫu nhiên).

**Giới hạn đã biết — reviewer và generator cùng họ model:** generator `openai/gpt-oss-120b` và reviewer
`openai/gpt-oss-20b` cùng họ gpt-oss (cùng nhà phát triển, nhiều khả năng cùng dữ liệu huấn luyện / cách hiểu
tiếng Việt). Hệ quả: lỗi **tương quan** — nếu generator hiểu sai hướng của một luận điểm (vd phủ định kép,
kiến nghị dạng "Nên cấm X"), reviewer cùng họ có thể hiểu sai y như vậy và **không bắt được** lật phe. Reviewer
khác họ (vd Qwen trên Groq, hoặc Claude / Gemini) sẽ độc lập hơn nhưng chưa thử (chi phí, JSON schema strict
chưa kiểm chứng). Cấu hình được qua `STANCE_REVIEW_PROVIDER` / `STANCE_REVIEW_MODEL`. Muốn đo mức độ ảnh
hưởng cần bộ case file gắn nhãn tay (mục 6).

### 2.4h. Rate limit: chờ theo provider, tách chỉ số, năng lực phục vụ (2026-09-26)

**Sự cố:** 3 batch v3 thật (15:45, 15:48, 17:14) đều hỏng ~9/20 lần chạy vì Groq 429 — chuyển vào
`experiments/case_plan/invalid/` (README lý do). Nguyên nhân: (1) retry 429 chờ **cố định 3s** × 4 trong khi Groq
yêu cầu **7–25s**; (2) batch nghỉ 5s giữa các lần chạy; (3) batch 15:45 và 15:48 chạy song song, chung hạn mức.
Bảng tổng hợp cũ còn báo "retry trung bình = 0.0" **sai**: chỉ số trộn lượt 429 với retry nội dung và loại bỏ các lần
retry nội dung bị 429 chặn (vd M10 con: 1 retry vì cụm cấm, rồi 5 lần 429 → đếm thành 0).

**Sửa:**
1. **Chờ theo provider** (`client.rate_limit_wait_seconds`): header `retry-after-ms` / `retry-after` (giây) nếu
   có, không thì parse "Please try again in Xs" trong message (hỗ trợ `9.9225s`, `1m2.5s`, `540ms`); chờ **đúng
   thời gian đó + jitter 1–2s** (`RATE_LIMIT_JITTER_SECONDS`, tránh nhiều request gọi lại cùng lúc). Không có gợi
   ý → `CASE_PLAN_RATE_LIMIT_WAIT_SECONDS` (3s) + jitter. Vẫn tối đa `CASE_PLAN_RATE_LIMIT_RETRIES` (4) lần chờ và
   **tổng thời gian vẫn bị `CASE_PLAN_TOTAL_BUDGET_SECONDS` chặn** (wait_for). Thời gian đã chờ lưu ở
   `opponent_llm_calls.rate_limit_wait_ms` (migration `0006`).
2. **Tách 2 chỉ số** (JSONL mỗi lần chạy + bảng tổng hợp + `compare_case_plan_batches`):
   - `content_retries` = số lần thử lại Case Planning vì output không hợp lệ (schema, validator, cụm cấm,
     side_flip) = số lần thử `case_plan` có `retry_feedback` (phản hồi chỉ sinh ra khi thực sự retry). **Chỉ số
     chất lượng prompt.**
   - `rate_limit_waits` = số lần + tổng giây chờ 429. **Phản ánh tải / hạn mức, không phải prompt.** Lượt chờ 429
     **không** tính vào `CASE_PLAN_MAX_ATTEMPTS` (đã đúng từ trước, giờ có test riêng).
3. **Batch:** mặc định `--pause 35`; in `tokens_in` / `tokens_out` **thực tế** của từng lần gọi (lấy từ `usage` của
   provider — `LLMClient.last_usage`, lưu `opponent_llm_calls.tokens_in/out`); bảng in `tokens_out` trung bình và
   lớn nhất của `case_plan` cạnh `CASE_PLAN_MAX_TOKENS`. **Chưa đổi `max_tokens` (4000)**: `tokens_out` của gpt-oss
   gồm cả token suy luận — hạ quá thấp sẽ cắt cụt JSON; quyết định sau khi có số liệu `tokens_out` max thật.
   `--only-failed <file.jsonl>`: chỉ chạy lại cấu hình `llm_error` của file cũ (giữ `run_index` gốc, ghi
   `rerun_of`, file `<ts>_<version>_rerun.jsonl`, mặc định dùng prompt_version của file cũ).
4. `last_usage` là trạng thái trên instance client — không an toàn nếu 1 instance bị gọi **đồng thời**; hiện đúng
   vì service tạo client mới cho mỗi request và batch chạy tuần tự.

**GIỚI HẠN NĂNG LỰC PHỤC VỤ — cần nêu trong báo cáo:** Groq free tier giới hạn **8000 token/phút (TPM)** cho
`openai/gpt-oss-120b`, và Groq tính **cả `max_tokens` xin trước** vào hạn mức (lỗi thật: "Limit 8000, Used 5291,
Requested 4032"). Mỗi lần gọi Case Planning xin ≈ 4000 token (prompt ~1000 + `max_tokens` 4000 được đặt trước) →
**≈ 2 lần Case Planning mỗi phút cho TOÀN hệ thống**, không phải mỗi người dùng. Retry (nội dung) cũng tiêu hạn mức.
Stance Reviewer dùng model khác (`openai/gpt-oss-20b`) nên có hạn mức riêng. Hệ quả: với free tier, hệ thống chỉ
phục vụ được vài phiên luyện tập bắt đầu cùng lúc; phiên thứ 3 trong cùng phút phải chờ 429 (tối đa trong budget
240s rồi 504). Hướng mở rộng (ngoài phạm vi capstone): nâng Groq Dev Tier, hạ `max_tokens` sau khi đo, hàng đợi /
xử lý bất đồng bộ cho Case Planning, hoặc provider trả phí.

### 2.4i. Công cụ đánh giá: so sánh phiên bản + gán nhãn mù (2026-09-27)

Chi tiết cách dùng: README mục 7. Cả 3 script chỉ đọc JSONL (không LLM, không DB), hàm chung ở
`scripts/eval_common.py`.

- **`compare_case_plan_batches.py`** (viết lại): `--v3 f1 f2 … --v4 f3 …` gộp nhiều file mỗi phiên bản (chạy lặp).
  File `--only-failed` (có `rerun_of`) thay lần chạy `llm_error` cùng `run_index` của file gốc trong cùng nhóm —
  **tự quyết** (spec không nói): nếu không, lần chạy hỏng vì 429 vẫn kéo tỷ lệ thành công xuống. Chỉ so cấu hình
  `(motion, ai_side, difficulty)` chung, in cấu hình thiếu; mỗi cấu hình có thể có nhiều lần chạy — chỉ số tính trên
  mọi lần chạy của cấu hình chung. Cảnh báo khi file trong nhóm `--v4` có `prompt_version` khác v4 (và ngược lại).
  `vague_evidence` của **case file cuối** tách 3 nhóm `ai_fields` / `learner_claim` / `unknown` (dạng cũ list chuỗi):
  số case file có hit (trên số case file thành công), tổng hit, hit theo cụm.
- **`label_stance.py`** — gán nhãn phe MÙ để đo độ chính xác của reviewer (việc còn treo ở mục 2.4e/2.4g). Mẫu =
  lần thử case_plan đã được reviewer đánh giá **có position từng mục** (lần reviewer lỗi bị bỏ: không có gì để đối
  chiếu). Mù: không hiện ai_side, độ khó, verdict, lý do reviewer; `--include` (ca M08 con easy trong `invalid/`, lần
  thử #3 reviewer báo A1 lật phe) được **trộn thứ tự theo seed** cùng mẫu ngẫu nhiên để người gán không biết mẫu nào
  là ca đặc biệt. CSV chỉ lưu định danh mẫu + nhãn người (không chép ai_side / reviewer vào CSV); report đọc lại JSONL
  nguồn theo `source_path`. Ngoài đối chiếu theo mục (đồng thuận, nhầm lẫn 3×3, lật phe theo người, bất đồng + lý do
  reviewer), report thêm **kết luận theo mẫu** (áp logic `judge()` cho nhãn người) vs verdict reviewer.
- **`label_vague_evidence.py`** — gán nhãn từng hit (a / l / n / s) → precision detector = a / (a + n). Hit dạng cũ
  (không có tên trường): tìm trường đầu tiên chứa cụm **chỉ để hiển thị**, nhóm vẫn là `unknown`.

**Phát hiện khi chạy thử (chỉ đọc) trên batch v3 sạch `20260927-092737`:** câu *"một số **nghiên cứu (không nêu cụ
thể) cho thấy**…"* (planned_response) **lọt validator cụm cấm** — mẫu `nghiên cứu cho thấy` khớp nguyên văn, có chữ
chen giữa là trượt. Detector (chỉ log) vẫn bắt được. Chưa sửa (ngoài phạm vi lượt này) — xem mục 6.

### 2.4j. Đánh giá v3/v4 bằng nhãn tay → sửa lỗi tổng hợp, prompt v5 (2026-09-29)

**Dữ liệu:** batch sạch v3 `20260927-092737` và v4 `20260927-094713` (mỗi batch 20 lần chạy, 0 lần chờ 429 — phần sửa
rate limit mục 2.4h có hiệu quả). Nhãn tay của Khoa: `experiments/labels/vague_evidence_labels.csv` (28 hit của bộ dò
cũ: 13 ở v3, 15 ở v4) và nhãn phe gán mù bằng `label_stance.py`: đợt 1 `stance_labels.csv` (7 mẫu) + đợt 2
`stance_labels_round2.csv` (10 mẫu, seed 7). (`*_old.csv` là lần gán dở dang, không dùng.)

**Bảng hiệu chỉnh bằng nhãn tay** — chỉ số tự động vs sau khi người đọc lại:

| Chỉ số | v3 tự động | v3 sau nhãn tay | v4 tự động | v4 sau nhãn tay |
|---|---|---|---|---|
| Thành công | 20/20 | 20/20 | 18/20 | 18/20 — **cả 2 thất bại do lỗi phía hệ thống**, không phải nội dung: M03 con hard (gõ sai tên trường 2 lần), M10 con medium (reviewer báo lật phe **sai** + lần 3 gõ sai tên trường) |
| Lật phe (reviewer bắt) | 0 | 0 — *(M06 pro A2: [CHỜ XÁC NHẬN] — có thể là lỗi gõ phím của người gán nhãn, xem dưới)* | 1 | **0 thật** — M10 A3 là báo nhầm (xem dưới) |
| Case file có "bằng chứng mơ hồ" (bộ dò cũ) | 10/20 (13 hit) | **1** thật (M05 run 8 "một số nghiên cứu (không nêu cụ thể) cho thấy") | 8/18 (10 hit) | **1** thật (M05 run 8 "nhiều sinh viên đã chứng minh…") |
| Groq từ chối schema | 1 | 1 — mảng `arguments` có phần tử rỗng `""` | 4 | 4 — **3 lần gõ `motion_interinterpretation`**, 1 lần vỡ cấu trúc (M07: phần sau object bị nhét vào mảng `arguments` dạng chuỗi) |

- **Bộ dò bằng chứng mơ hồ cũ: precision 2/28 (7%)** (v3 1/13, v4 1/15). 16/16 hit "%" là bắt nhầm (số trong ví dụ
  "Giả sử" — được phép); "nghiên cứu" / "chứng minh" / "chuyên gia" phần lớn dùng nghĩa thường ("trung tâm nghiên
  cứu", "cơ hội chứng minh", "gặp gỡ các chuyên gia").
- **Stance Reviewer v1 (chỉ đọc claim)** — đồng thuận người vs reviewer:

  | Đợt | Mẫu | Luận điểm | Weighing | Ghi chú |
  |---|---|---|---|---|
  | 1 (`stance_labels.csv`) | 7 | **18/20** | *loại* (7 mục) | định nghĩa nhãn "không rõ" lúc đó chưa rõ (gộp cả "trung lập") → người đánh weighing "không rõ" hàng loạt; không so được |
  | 2 (`stance_labels_round2.csv`, seed 7, định nghĩa đã sửa) | 10 | **22/22** | **10/10** | 32/32 |
  | **Tổng luận điểm** | 17 | **40/42 (95%)** | 10/10 (chỉ đợt 2) | |

  2 bất đồng (đều ở đợt 1):
  - (a) **M06 pro A2** *"Tuần làm việc 4 ngày giúp doanh nghiệp giảm chi phí vận hành hàng tuần"* (v3 run 10, lần thử #1):
    người `p`, reviewer `u`. **[CHỜ XÁC NHẬN: có thể là lỗi gõ phím của người gán nhãn — nếu đúng, bất đồng này không
    tính và đồng thuận luận điểm là 40/41.]**
  - (b) **M10 con medium v4 A3** *"Giá tăng do thuế **không chắc chắn** dẫn đến giảm đáng kể việc tiêu thụ…"* (lần thử
    #1): reviewer **đảo nghĩa phủ định** → đọc thành ủng hộ; người đánh phản đối (đúng phe, reasoning nói rõ "không chỉ phụ
    thuộc vào giá cả") → **false positive**: case file đúng phe bị reject, lần chạy hết lượt.

  **Lưu ý:** toàn bộ mẫu chỉ có **2 ca reviewer báo lật phe** (M08 con easy lần thử #3 — đúng; M10 con medium v4 lần thử
  #1 — sai) → **chưa đủ để ước lượng độ chính xác phát hiện lật phe** (precision / recall của verdict `side_flip`). Tỷ lệ
  đồng thuận 95% là theo từng luận điểm, phần lớn là các luận điểm dễ, đúng phe.
  Để so v1 / v2 trên **cùng** các lần thử đã gán nhãn (thay vì chờ batch mới): `scripts/replay_stance_review.py`
  (README bước 5) — chạy lại reviewer với LLM thật, tách luận điểm / weighing, in riêng 2 ca M08 / M10, `--compare`.
  **Chưa chạy** (Khoa tự chạy).
- **Lỗi gõ tên trường:** `motion_interinterpretation` xuất hiện ở mẫu v2 số 2 và 3/4 lần Groq từ chối ở v4 — lỗi lặp của
  gpt-oss-120b với token "interpretation". Phản hồi retry cũ chỉ chép thông báo Groq ("missing 'motion_interpretation'"
  — Groq chỉ báo lỗi jsonschema **đầu tiên**, không báo key lạ) → model lặp nguyên lỗi (M03: 2/2 lần).
- `tokens_out` case_plan v4: trung bình 2001, lớn nhất 2653 (< `max_tokens` 4000 — chưa đổi).

**Thay đổi và lý do:**

1. **Tên trường** `motion_interpretation` → **`motion_reading`** (schema, prompt, validator, test; migration `0007` đổi
   key JSONB case file cũ, có downgrade). Lý do: bỏ token hay bị lặp. Mẫu JSON dùng chung nên prompt v3 / v4 cũng đổi
   **đúng tên trường này** (nội dung khác không đổi) — so sánh batch trước / sau chỉ khác tên trường.
2. **Tự sửa tên trường khi Groq từ chối schema** (`_try_key_repair`): `failed_generation` parse được → với mỗi object
   (case file + từng definition / argument / anticipated), key lạ có **khoảng cách Levenshtein ≤ 3** tới một key bắt buộc
   đang thiếu (duy nhất, không mơ hồ) → đổi tên → validate **cục bộ** (CaseFile + số luận điểm + bằng chứng mơ hồ HIGH).
   Qua → chấp nhận, **không gọi lại LLM**, dòng log `success=true`, `schema_rejected=true`, `key_repairs =
   {"event": "key_repaired", "renames": [{path, from, to}], "provider_error"}`; case file vẫn qua Stance Reviewer. Không
   sửa được / vẫn không hợp lệ → retry có phản hồi như cũ. Lưu ý: `motion_interinterpretation` → `motion_reading` cách
   > 3 nên **không** tự sửa — tên mới được chọn để model không sinh ra lỗi này nữa; bước tự sửa dành cho lỗi gõ nhỏ.
3. **Phản hồi retry do schema nêu CẢ key thiếu lẫn key lạ** (`key_issues`): "bạn đã viết 'X', tên đúng là 'Y'" (khi ≤ 3),
   "trường lạ … — bỏ đi", "thiếu trường bắt buộc". Áp dụng cho cả Groq từ chối (đọc `failed_generation`) lẫn kiểm tra cục
   bộ (không JSON schema / provider khác).
4. **`CASE_PLAN_MAX_ATTEMPTS` 2 → 3** (vẫn trong budget 240s): M10 con v4 hết lượt sau 1 side_flip + 1 schema_rejected.
5. **Stance Reviewer v2** (`stance_review_v2`, mặc định; v1 giữ nguyên, chọn bằng `STANCE_REVIEW_PROMPT_VERSION`): mỗi
   argument gửi **claim + reasoning** (vẫn KHÔNG có phe), system prompt nhắc chú ý phủ định / mức độ chắc chắn. Test hồi
   quy dùng nguyên văn A1–A3 + weighing của M10 (mock LLM; kiểm tra prompt chứa reasoning của A3). **Chưa kiểm chứng với
   LLM thật** — cần chạy lại / gán nhãn để biết v2 có hết báo nhầm M10 không.
6. **Bộ dò bằng chứng mơ hồ làm lại** (`app/opponent/vague_detector.py`, thay `VAGUE_EVIDENCE_PHRASES` + validator 4 cụm):
   - **HIGH → validator reject** (retry có phản hồi; chỉ trong khẳng định của AI, `learner_claim` hạ xuống LOW):
     `nghiên cứu` + ≤ 5 từ + (cho thấy | chỉ ra | khẳng định | phát hiện | chứng minh); `đã (được) chứng minh` khi 6 từ
     trước KHÔNG có chúng tôi / chúng ta / phe / đội; `chuyên gia` + ≤ 3 từ + (cho rằng | khuyến cáo | nhận định | đánh giá);
     (nhiều | một số | các) + danh từ 1–4 âm tiết + đã (được) + (chứng minh | áp dụng thành công | cho thấy);
     **tự quyết thêm** (nhiều | một số | các) (quốc gia | nước | nơi) … đã (được) áp dụng — giữ từ validator cũ vì có
     bằng chứng thật (v3 chạy lại mẫu 2: "nhiều quốc gia đã áp dụng mô hình này mà vẫn…", mục 2.4d), mẫu spec chỉ bắt
     "áp dụng thành công".
   - **LOW → chỉ log**: "nghiên cứu", "chuyên gia", "thống kê / theo báo cáo", "nhiều quốc gia / nhiều nước", "%" —
     **không quét số / "%" trong `example` và `definitions`**. Mỗi đoạn khớp ghi 1 hit (HIGH ưu tiên).
   - Log: `vague_evidence = [{phrase (nhãn quy tắc), field, level, rule, match}]`. `failure_kind` vẫn là `banned_phrase`
     (liên tục với batch cũ).
   - **Quy trình:** quy tắc thiết kế **chỉ trên nhãn v3** (13 nhãn: 1 `a`, 12 `n`), chốt, rồi mới chạy
     `scripts/eval_vague_detector.py` trên v4 — **không chỉnh quy tắc sau khi xem v4**. (Trước khi chạy v4 có sửa 1 chỗ
     theo ngữ nghĩa spec, không theo dữ liệu v4: danh từ tiếng Việt tính theo âm tiết nên cho 1–4 thay vì 1–3 —
     "giải pháp thay thế" = 4.)

   | Tập | Bộ dò cũ (precision) | Mới HIGH: hit / đúng / nhầm | Nhầm bị reject | Bỏ sót nhãn `a` | Mới LOW (chỉ log) |
   |---|---|---|---|---|---|
   | v3 — thiết kế | 1/13 (8%) | 1 / 1 / 0 | 0 | 0 | 4 hit: 3 `n`, 1 chưa có nhãn (learner_claim "Các quốc gia đã áp dụng…") |
   | **v4 — kiểm tra** | 1/15 (7%) | **1 / 1 / 0** | **0** | **0** | 4 hit: 4 `n` |

   **Giới hạn:** mỗi tập chỉ có **1** nhãn `a` → "precision 1/1" gần như không có sức nặng thống kê; điều đo được chắc hơn là
   **0/26 hit bắt nhầm bị reject** và 2/2 nhãn `a` vẫn bị bắt. Nhãn chỉ có cho hit của bộ dò cũ — hit mới mà bộ dò cũ
   không có (vd mẫu "các quốc gia … đã áp dụng") cần gán tay (mục "chưa có nhãn" của script). LOW vẫn nhiều bắt nhầm
   (chấp nhận được vì chỉ log).
7. **Prompt v5** (`case_plan_v5.py`, mặc định; v3, v4 giữ): thêm nguyên văn 2 quy tắc (11: số trong tình huống giả định
   hợp lý, không gắn địa điểm / tổ chức / thiết bị đo có thật; 12: không khẳng định điều đã xảy ra với chủ thể chung chung).
   Lý do: nhãn tay cho thấy ví dụ "Giả sử" hay gắn số với địa danh thật ("Giả sử ở Hà Nội … 30% là xe máy"), và hit thật
   duy nhất ở v4 là "nhiều sinh viên đã chứng minh…" (quan sát chung chung, lọt validator cũ). **Chưa chạy batch v5.**

### 2.4k. Replay reviewer v1 / v2 → mặc định quay về v1, thêm v3; tăng token reviewer (2026-09-29)

**Kết quả replay** (Khoa chạy `replay_stance_review` trên 17 mẫu đã gán nhãn; `experiments/reviewer_replay/`
`20260929-142106_stance_review_v1.jsonl`, `20260929-142613_stance_review_v2.jsonl`; so sánh bằng `--compare`):

| | v1 (chỉ claim) | v2 (claim + reasoning) |
|---|---|---|
| Đồng thuận luận điểm | 40/42 (95%) | 37/39 (95%) — 1 mẫu lỗi |
| Đồng thuận weighing (đợt 2) | 10/10 | 10/10 |
| Lỗi gọi reviewer | 0 | **1** — M04 con medium (v3 run 7): Groq 400 *"max completion tokens reached before generating a valid document"* ở `max_tokens` 1500 |
| M10 con medium v4 A3 (phủ định) | `ung_ho` (sai) | **vẫn `ung_ho` (sai)** — lý do: "Thuế cao giảm tiêu thụ đồ uống có đường" (bỏ qua "không chắc chắn") |
| M08 con easy #3 (lật phe thật) | `side_flip` (đúng) | `side_flip` (đúng) |
| Mục đổi kết luận v1 → v2 | — | **0** (ngoài mẫu lỗi) |

→ v2 không sửa được lỗi nó nhắm tới (chỉ *nhắc* chú ý phủ định, model vẫn kết luận thẳng), lại tốn token hơn và bị cắt 1
lần. **Mặc định quay về `stance_review_v1`** (v2 giữ, chọn được). Bất đồng M06 pro A2 giống hệt ở v1 và v2 (vẫn chờ xác nhận
có phải lỗi gõ phím của người gán nhãn — mục 2.4j).

**Thay đổi:**
1. **`STANCE_REVIEW_MAX_TOKENS` 1500 → 2000** (Settings; replay dùng đúng giá trị này, ghi vào kết quả cùng `tokens_in` /
   `tokens_out`). Căn cứ: `tokens_out` reviewer v1 trong batch v4 395–1217; v2 vượt 1500 ít nhất 1 lần; v3 còn viết thêm
   `restatement` cho mỗi mục; gpt-oss tính cả token suy luận. Reviewer chạy model riêng (gpt-oss-20b) nên không ăn vào
   TPM của model sinh case (mục 2.4h).
2. **`stance_review_v3`** (giữ v1, v2): input như v2 (claim + reasoning, KHÔNG có phe); mỗi luận điểm và weighing trả
   **theo thứ tự `restatement` → `effect` → `reason`**:
   - `restatement`: diễn đạt lại thành MỘT câu đơn giản, không phủ định lồng — buộc model *hiểu câu* trước;
   - `effect`: trả lời "Nếu luận điểm này đúng, kiến nghị trở nên mạnh hơn hay yếu đi?" (`manh_hon` / `yeu_di` / `khong_ro`)
     — câu hỏi hướng tác động đơn giản hơn "bảo vệ phe nào";
   - code ánh xạ `manh_hon` → `ung_ho_kien_nghi`, `yeu_di` → `phan_doi_kien_nghi`; `judge()` / `side_flip` giữ nguyên.
   - Thứ tự trường trong JSON schema là restatement → effect → reason (và prompt yêu cầu đúng thứ tự): model sinh tuần tự nên
     câu diễn đạt lại có trước kết luận. Lưu ý: strict schema của Groq kiểm tra SAU khi sinh (mục 2.4d) — thứ tự dựa vào
     prompt + schema, không phải ràng buộc lúc sinh.
   - Log: mỗi mục trong `reviewer_detail.positions` có thêm `restatement`, `effect`.
   - Mỗi phiên bản reviewer là bộ ba prompt / schema / parse (`stance_reviewer.REVIEW_VERSIONS`), service và replay dùng chung.
3. Replay hỗ trợ `--reviewer-version v3`; báo cáo in câu diễn đạt lại ở 2 ca đặc biệt và `tokens_out` lớn nhất.
**Chưa chạy replay v3 thật** (Khoa tự chạy).

### 2.4l. Replay reviewer v1 / v2 / v3 trên 17 mẫu đã gán nhãn → mặc định v3 (2026-09-29)

**Phương pháp:** chạy lại reviewer (`scripts/replay_stance_review.py`) trên **đúng** các lần thử đã gán nhãn mù (đợt 1 +
đợt 2, mục 2.4j — 17 mẫu, 42 luận điểm + 10 weighing đợt 2), cùng model `openai/gpt-oss-20b`, **temperature 0**, JSON
schema. Replay **v1 tái hiện chính xác** kết quả lúc chạy batch: 40/42 luận điểm, cùng 2 bất đồng, cùng verdict ở 2 ca đặc
biệt — kiểm tra từng mục: **59/59 position (luận điểm + weighing) và mọi verdict trùng với log batch** → replay là phép đo
ổn định, khác biệt giữa các phiên bản là do prompt chứ không do ngẫu nhiên.
File: `experiments/reviewer_replay/20260929-142106_stance_review_v1.jsonl`, `…-142613_stance_review_v2.jsonl`,
`…-160134_stance_review_v3.jsonl`.

| | v1 | v2 | v3 |
|---|---|---|---|
| M10 v4 #1 (false positive do phủ định) | side_flip | side_flip | **pass** |
| M08 #3 (lật phe thật) | side_flip | side_flip | side_flip |
| Đồng thuận luận điểm | 40/42 | 37/39 | **41/42** |
| Đồng thuận weighing (đợt 2) | 10/10 | 10/10 | 10/10 |
| Lỗi gọi / cắt output | 0 | 1 (M04 con, cắt ở 1500 token) | 0 |
| tokens_out lớn nhất | — | — | 1491 / 2000 |

(Replay v1 / v2 chạy trước khi script ghi token nên cột token trống.) So với v1, v3 đổi **đúng 1 mục**: M10 A3 `ung_ho` →
`phan_doi` (khớp nhãn người), kéo verdict M10 từ `side_flip` về `pass`.

**Cơ chế:** v1 và v2 đều ghi lý do kiểu "thuế cao giảm tiêu thụ" — bỏ mất phủ định "không chắc chắn" (v2 có reasoning và lời
nhắc chú ý phủ định nhưng vẫn kết luận thẳng). v3 diễn đạt lại TRƯỚC khi kết luận: `restatement` = *"Thuế cao có thể không
làm giảm đáng kể tiêu thụ đồ uống có đường vì thói quen tiêu dùng không phụ thuộc nhiều vào giá."* → `effect` = `yeu_di` →
đúng. Thay đổi then chốt: (1) câu hỏi **"Nếu luận điểm này đúng, kiến nghị mạnh hơn hay yếu đi?"** — trùng với câu hỏi dùng
khi gán nhãn tay; (2) **bắt buộc diễn đạt lại trước** khi trả lời.

**Bất đồng còn lại:** M06 pro A2 (tuần 4 ngày) — **[CHỜ XÁC NHẬN lỗi gõ phím của người gán nhãn; nếu đúng thì 42/42]**.

**Hạn chế:**
- (a) v3 được thiết kế **SAU** khi biết ca M10 → nguy cơ khớp quá mức (overfit vào đúng ca đã thấy). Bằng chứng hiện có:
  41 mục còn lại không mục nào đổi theo hướng sai. Cần kiểm chứng trên dữ liệu mới (batch v5 + gán nhãn).
- (b) Chỉ có **2 ca lật phe** được reviewer báo trong toàn bộ mẫu (1 đúng M08, 1 sai M10) → chưa ước lượng được độ chính xác
  phát hiện lật phe.

**Quyết định:** mặc định reviewer = **`stance_review_v3`** (`STANCE_REVIEW_PROMPT_VERSION`; v1, v2 giữ lại). `.env` của Khoa
không ghi đè biến này nên chỉ đổi mặc định trong code + `.env.example`.

### 2.4m. Batch v5: reviewer v3 báo sai 3/3 side_flip → quay về v1 + retry trung tính cho lật phe (2026-09-29)

**Dữ liệu:** batch `experiments/case_plan/20260929-163008_case_plan_v5.jsonl` (reviewer v3 lúc chạy). Reviewer báo
side_flip 3 lần: M05 con easy (run 9) #1, #4; M09 con hard (run 17) #1. Người gán nhãn **mù** (`stance_labels_v5.csv`):
**0 lật phe**, 6 mục reviewer chấm `u` mà người chấm `p`. Replay v1 trên đúng 5 lần thử bị gắn cờ (3 lần bị báo + lần được
chấp nhận ngay sau mỗi lượt chạy): `experiments/reviewer_replay/20260929-195157_stance_review_v1_from-batch.jsonl`
(`replay_stance_review --from-batch … --only-flagged --reviewer-version v1`).

| | v3 (lúc chạy batch) | v1 (replay) |
|---|---|---|
| Verdict trên 5 lần thử bị gắn cờ | 3 side_flip (đều báo sai) + 2 pass | **5/5 pass** |
| Đồng thuận với nhãn người (13 mục có nhãn: M05 #1, #4, #7; M09 #1) | 7/13 | **13/13** |

**Cơ chế lỗi của v3:** v3 diễn đạt lại từng mục rồi hỏi "kiến nghị mạnh hơn hay yếu đi?". Với các mục tự nêu kết luận,
v3 coi **kết luận của chính mục** là "kiến nghị":
- M05 ("Sinh viên nên đi làm thêm trong thời gian học đại học") #4, restatement weighing: *"Lợi ích ngắn hạn của làm thêm
  không bù đắp được thiệt hại dài hạn về học tập và sức khỏe, **nên phản đối làm thêm** trong thời gian học đại học."* →
  `manh_hon`. Câu này làm kết luận của nó mạnh hơn, còn kiến nghị của motion thì yếu đi.
- M09 ("Người trẻ nên ở lại quê hương lập nghiệp **thay vì** lên thành phố") #1: A1 được diễn đạt lại thành *"Người trẻ
  nên lên thành phố vì mức lương và cơ hội việc làm cao hơn."* → `manh_hon`; tương tự A2, A3, weighing. Motion dạng
  "A thay vì B" có hai đề xuất đối lập trong cùng một câu, nên "kiến nghị" càng dễ bị hiểu nhầm là B.
- v1 luôn đối chiếu với motion. Lý do v1 ở M09 #1 A1: *"Mức lương và cơ hội việc làm cao hơn ở thành phố làm cho **đề
  nghị ở lại quê hương** trở nên kém hấp dẫn."* → phản đối, đúng.

**Generator có đổi phe không:** M09 #1 nhận phản hồi retry (có ghi weighing "đang bảo vệ phe Đề xuất") → #3 được chấp
nhận; weighing #3 nhắc thẳng motion ("phe Phản đối, cho rằng người trẻ không nên ở lại quê hương mà nên lên thành
phố"). Generator **KHÔNG** đổi phe. M05 cũng giữ đúng phe sau 2 lần phản hồi sai. Tuy vậy rủi ro là có thật: một phản hồi
nói "bạn đang bảo vệ phe người học" trong khi case file đúng phe là **chỉ dẫn sai**, và model có thể làm theo.

**Quyết định:**
1. Mặc định reviewer = **`stance_review_v1`** (v2, v3 giữ lại để so sánh).
2. **Retry trung tính khi side_flip:** sinh lại từ prompt GỐC, **không** gửi phản hồi "bạn đã lật phe". Lần retry vẫn
   tính vào `CASE_PLAN_MAX_ATTEMPTS`; lần thử bị báo được đánh dấu `reviewer_detail.retry = "side_flip_neutral_retry"`
   (`retry_feedback` để trống, log `side_flip_neutral_retry`). `content_retries` của batch runner tính cả retry trung tính.
   Các lỗi khác (sai JSON / schema, validator, số luận điểm, bằng chứng mơ hồ HIGH, cụm cấm) **giữ** retry có phản hồi.
3. `replay_stance_review` mặc định nạp thêm `stance_labels_v5.csv` (đợt 3; tổng 23 mẫu), nên mọi lần replay sau đều có
   các ca motion dạng "A thay vì B".

**Hạn chế đã biết của v1:** báo sai M10 (phủ định mơ hồ trong claim: "không chắc chắn dẫn đến giảm…", mục 2.4k). Giảm
thiểu: (a) generator được yêu cầu tránh phủ định lồng (việc còn treo); (b) nhờ retry trung tính, một lần báo sai chỉ tốn
**một lượt thử**, không kéo generator lệch phe.

**Bài học:** v3 cải thiện trên dữ liệu dùng để thiết kế (41/42, mục 2.4l) nhưng thất bại trên dữ liệu mới → **overfitting**
vào ca M10 đã thấy. Phát hiện được nhờ **gán nhãn mù trên batch mới**, không phải nhờ replay trên dữ liệu cũ. Mọi thay đổi
reviewer về sau cần được kiểm chứng trên dữ liệu chưa dùng khi thiết kế.

**Ý tưởng cho reviewer tương lai (CHƯA làm):** luôn trích **nguyên văn motion** trong câu hỏi thay vì dùng chữ "kiến nghị"
đơn lẻ (vd "Nếu luận điểm này đúng, lập luận cho '<motion>' mạnh hơn hay yếu đi?"); bộ kiểm tra phải có motion dạng "A
thay vì B".

### 2.5. Tổng kết đánh giá Case Planning (2026-09-29 — tóm tắt để trích vào báo cáo)

Dữ liệu: 3 batch × 20 lần chạy (10 motion × 2 phe, độ khó xoay vòng) — `experiments/case_plan/20260927-092737_case_plan_v3.jsonl`,
`20260927-094713_case_plan_v4.jsonl`, `20260929-163008_case_plan_v5.jsonl`. Planner `openai/gpt-oss-120b`, reviewer
`openai/gpt-oss-20b` (Groq).

**1. Độ ổn định.** Batch v5: **20/20 thành công** (`final_status = ready`), **0 lần Groq từ chối schema**. Trước đó các lần
từ chối schema chủ yếu do model gõ sai tên trường dài `motion_interpretation`; sau khi đổi thành `motion_reading` (kèm tự
sửa tên trường gõ sai ≤ 3 ký tự, mục 2.4j) thì không còn lần nào. Rate-limit (TPM của Groq) được xử lý bằng cách chờ đúng
thời gian provider yêu cầu (`retry-after` / "try again in …s") và nghỉ 35s giữa các lần chạy batch (`--pause 35`, mục
2.4h). Batch v5 có 2 lần 429, cả hai đều qua được sau khi chờ, không lần chạy nào thất bại vì rate-limit.

**2. Lật phe.** Reviewer v1 (mặc định) so với nhãn **mù** của người trên **23 mẫu**:

| Đợt | Mẫu | Đồng thuận |
|---|---|---|
| 1 (`stance_labels.csv`) | 7 | luận điểm **18/20** (weighing loại — định nghĩa nhãn lúc đó chưa rõ, mục 2.4j) |
| 2 (`stance_labels_round2.csv`) | 10 | **32/32** (22 luận điểm + 10 weighing) |
| 3 (`stance_labels_v5.csv`, replay v1 trên các lần thử bị v3 gắn cờ) | 6 | **13/13** mục trên 4 lần thử có nhãn (mục 2.4m) |

Khi reviewer báo side_flip: **retry trung tính** (sinh lại từ prompt gốc, không phản hồi "bạn đã lật phe"), nên một lần
báo sai chỉ tốn một lượt thử (mục 2.4m). **Hạn chế:** trong toàn bộ mẫu chỉ có **rất ít ca lật phe thật** (M08 #3, mục
2.4j), nên chưa ước lượng được độ nhạy (recall) phát hiện lật phe. Con số trên chủ yếu đo khả năng **không báo sai**.

**3. Reviewer v3 bị loại do overfitting.** v3 (diễn đạt lại → "mạnh hơn / yếu đi") đạt 41/42 trên dữ liệu dùng để thiết kế
(mục 2.4l) nhưng **báo sai 3/3 side_flip** trên dữ liệu mới (batch v5): nó coi kết luận của chính luận điểm là "kiến nghị".
Motion dạng "A thay vì B" là ca khó. Chi tiết: mục 2.4m.

**4. Bịa bằng chứng (bộ dò `vague_detector`).**
- **Bộ dò cũ** (một danh sách cụm từ phẳng): precision **2/28 (7%)** trên v3 + v4 (v3 1/13, v4 1/15). Phần lớn hit là bắt
  nhầm, vd 16/16 hit "%" là số trong ví dụ "Giả sử" (mục 2.4j).
- **Bộ dò mới** (HIGH = reject + retry có phản hồi; LOW = chỉ log): mức HIGH **0 reject nhầm** trên **35 hit có nhãn**
  (v3 + v4 + v5; thêm 1 hit `learner_claim` gán `l` ở điểm 6 → 36). Các ca HIGH bắt đúng:
  - v3: "một số **nghiên cứu (không nêu cụ thể) cho thấy**…" (`planned_response`);
  - v4: "**nhiều sinh viên đã chứng minh** khả năng duy trì thành tích…";
  - v5, lúc chạy batch: "**nghiên cứu giả định cho thấy**" (M05 pro hard, run 8 #1, `planned_response`, luật
    `nghien_cuu_ket_luan`). Bị reject **trước** khi log `vague_evidence` nên không có trong `eval_vague_detector`.
  - Quy tắc được viết dựa trên nhãn v3 (tập thiết kế), rồi kiểm tra trên v4 + v5 (tập kiểm tra).
- **Bỏ sót ở v5:** "Chi phí hoạt động tăng **khoảng 15%** so với mô hình 5 ngày…" (M06, `arguments[1].impact`, nhãn `a`).
  Cách xử lý: sửa ở **prompt** (điểm 5), **không** nâng "%" lên HIGH, vì precision của "%" trong `impact` ở v5 chỉ là
  **1/2** (hit còn lại "Sản lượng giảm 20% so với mức trước…" là nhãn `n`). Reject theo "%" sẽ loại nhầm nhiều case
  hợp lệ.
- **Nguồn nhãn:** nhãn v3 / v4 là nhãn **độc lập** của người dùng. Nhãn v5 do **Claude đề xuất**, người dùng **rà soát và
  xác nhận**, nên độc lập kém hơn; khi trích dẫn cần ghi rõ điều này.

**5. Việc còn treo cho prompt Case Planning tiếp theo** (chưa làm):
- con số chỉ được xuất hiện trong `example` "Giả sử…";
- `impact` / `reasoning` không đưa con số mới (nguồn của ca bỏ sót "khoảng 15%");
- tránh phủ định lồng trong `claim` (nguồn báo sai M10 A3 của reviewer v1);
- con số giả định không gắn với địa điểm có thật.

**6. Hit chưa có nhãn đã được gán.** Hit "Các quốc gia đã áp dụng thuế đường…" (v3, M10 run 19 #2,
`anticipated_opponent_arguments[2].learner_claim`, luật `nhieu_noi_da_ap_dung`, mức LOW) trước đây chưa có nhãn vì bộ dò
cũ không bắt. Đã ghi vào `experiments/labels/vague_evidence_labels.csv` với nhãn **`l`** (dự đoán lời learner — hợp lệ,
người dùng xác nhận). `eval_vague_detector` giờ báo "chưa có nhãn = 0" ở cả tập thiết kế lẫn tập kiểm tra.

### 2.6. Test trên Postgres thật, không SQLite

Enum/UUID/JSONB là đặc thù Postgres. DB `ai_generation_test` trong cùng container; đầu phiên
pytest chạy Alembic `downgrade base → upgrade head` (kiểm tra migration luôn, thay vì
`create_all`); mỗi test 1 transaction ngoài + `join_transaction_mode="create_savepoint"`
nên `commit()` trong service không thoát ra ngoài, cuối test rollback.

### 2.7. Các chi tiết nhỏ

- `created_at`/`updated_at` dùng `clock_timestamp()` thay vì `now()`: `now()` cố định theo
  transaction → nhiều case file tạo trong cùng transaction (vd trong test) trùng `created_at`,
  "bản mới nhất" sai.
- `eager_defaults=True` trên mọi model: lấy giá trị server-side qua `RETURNING`, tránh lazy-load
  ngầm (không được phép với AsyncSession).
- Session kẹt ở `PLANNING` (process chết giữa chừng) quá `CASE_PLAN_STALE_AFTER_SECONDS` (360s) thì cho phép chạy lại (mục 2.4c).
- Enum lưu VALUE (`"pro"`) chứ không phải NAME (`"PRO"`) — DB và API dùng chung 1 giá trị.
- Downgrade migration xoá tay các enum type (autogenerate không tự làm).

### 2.8. Giai đoạn 3a: lượt tranh luận + baseline ngây thơ (2026-09-30)

**Format trận** — định nghĩa ở MỘT chỗ: `app/opponent/match_format.py` (`MATCH_FORMAT`).

| turn_index | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|
| Vòng | opening | opening | rebuttal | rebuttal | closing | closing |
| Phe | pro | con | pro | con | **con** | **pro** |

Lý do:
- **Rút gọn từ Lincoln-Douglas**, mỗi bên đúng **3 bài** (mở màn, phản bác, tổng kết). Đủ ngắn cho một buổi luyện tập,
  nhưng vẫn có đủ ba chức năng: dựng case, đánh case đối phương, cân nhắc tổng thể.
- **Tổng kết đảo thứ tự** (con trước, pro sau), như reply speech của WSDC / AP: phe Đề xuất nói đầu thì được nói cuối,
  bù cho bất lợi phải dựng case trước khi nghe đối phương. Hệ quả: phe con nói **2 bài liên tiếp** (4 → 5) và phe pro
  nhận **2 bài liên tiếp** của đối phương trước lượt cuối (4, 5 → 6).
- Độ dài mục tiêu (số từ, cấu hình được): opening 400, rebuttal 320, closing 260 (`TURN_TARGET_WORDS_*`). Số từ = số cụm
  cách nhau bởi khoảng trắng (mỗi âm tiết tiếng Việt là 1 từ, giống cách Word đếm). Ở 3a **chỉ ghi `word_count`, không
  reject theo độ dài**: cần dữ liệu thật trước khi đặt ngưỡng.

**4 chế độ sinh** (`turn_mode(turn_index, ai_side)`, hàm thuần):

| mode | Khi nào | Khác biệt |
|---|---|---|
| `opening_first` | AI pro, lượt 1 | chưa có bài nào của learner để đáp lại |
| `opening_reply` | AI con, lượt 2 | mở màn sau khi đã nghe mở màn của learner |
| `rebuttal` | lượt 3 / 4 | phản bác |
| `closing` | lượt 5 / 6 | tổng kết. AI con (5): ngay sau bài của chính mình, không có bài learner mới. AI pro (6): nhận 2 bài learner |

**Schema** (migration `0008`):
- `opponent_speeches` — snapshot mọi bài nói, UNIQUE(session_id, turn_index). Service **dựng lại trận từ bảng này**,
  không dựa vào Main Flow gửi lại toàn bộ lịch sử.
- `opponent_turns` — metadata lượt AI; `learner_claims` / `premises` / `target_premise` để sẵn cho bộ sinh đầy đủ (3b),
  baseline để NULL. `latency_ms` và `tokens_*` là tổng của mọi lần gọi trong lượt.
- `opponent_llm_calls.turn_id` (nullable) + `llm_call_purpose` thêm `turn`. `user_prompt` của lời gọi sinh bài nói lưu
  **JSON danh sách messages** (hội thoại gửi LLM). Lượt sinh **thất bại** vẫn log lời gọi, nhưng `turn_id` = NULL (chưa
  có dòng `opponent_turns`); tìm theo `session_id` + `purpose = turn`.
- Enum mới: `debate_round_type`, `speech_speaker`, `turn_mode`.

**API** `POST /opponent/sessions/{external_session_id}/turns`, body
`{turn_index, new_learner_speeches: [{turn_index, round_type, text}]}`; response
`{turn_index, round_type, mode, speech_text}`. `new_learner_speeches` = mọi bài learner **kể từ lượt AI trước** (có thể
rỗng). Text được chuẩn hoá NFC + strip; rỗng → 422 (Pydantic).
- 404: không có session. 409: session chưa `READY`.
- 400: `turn_index` không tồn tại / không phải lượt AI; bài learner sai `round_type`, rơi vào lượt của AI, nằm sau lượt AI
  được yêu cầu, hoặc gửi trùng.
- 409: thiếu lượt trước (không có trong DB và không có trong request; gồm cả lượt AI chưa sinh), hoặc bài learner đã lưu
  mà request gửi **nội dung khác** (không ghi đè snapshot).
- Idempotent: lượt AI đã có + mọi bài learner gửi kèm khớp snapshot → **200, trả kết quả cũ, không gọi LLM**; khác → 409.
  Sinh mới → **201** (như `POST /sessions`: 201 khi tạo, 200 khi idempotent).
- Lấy LLM client **trước** khi ghi DB (thiếu key → 503). Bài learner mới được ghi (`ON CONFLICT DO NOTHING`, rồi so lại
  nội dung) và commit **trước** khi gọi LLM, nên nếu sinh thất bại thì lần gọi lại không cần gửi lại bài learner.
- Race 2 request cùng lượt: bên ghi sau gặp UNIQUE → bỏ bài vừa sinh, trả bản đã lưu (log LLM vẫn ghi, `turn_id` NULL).
- Lỗi: bài rỗng sau `TURN_MAX_ATTEMPTS` (2) → 502; lỗi provider → 502; vượt `TURN_TOTAL_BUDGET_SECONDS` (120) → 504;
  429 → chờ theo provider rồi thử lại (dùng chung `CASE_PLAN_RATE_LIMIT_RETRIES` / `_WAIT_SECONDS`, không tính vào số lần
  thử).

**Bộ sinh** (`app/opponent/turn_generators.py`): interface `generate(mode, context) → TurnResult`, chọn bằng
`TURN_GENERATOR_VERSION`. Bộ sinh tự gọi LLM qua `LLMCaller` (xử lý 429, ghi mỗi lần gọi), nên bộ sinh nhiều bước ở 3b
cắm vào bên cạnh mà không phải sửa service. LLM client có thêm `generate_chat()`: nhận hội thoại nhiều tin, trả **văn bản
thuần** (không JSON mode). Ghi chú bản sao có chủ đích từ Evaluation service (mục 2.1) đã được cập nhật.

**`turn_baseline_v1` — CỐ Ý ngây thơ**, làm mốc so sánh cho 3b. Mô phỏng chatbot thông thường kiểu DEBO:
- System: *"Bạn là một người tranh luận thuộc phe {Đề xuất / Phản đối} về kiến nghị '{motion}'. Hãy tranh luận với
  người dùng."* + 1 câu chỉ dẫn theo mode + *"Độ dài khoảng N từ."* + *"Viết bằng tiếng Việt, văn nói, không dùng
  markdown hay gạch đầu dòng."*
- Lịch sử: toàn bộ bài nói trước đó dạng hội thoại (learner = `user`, AI = `assistant`), AI nói với learner ở ngôi thứ hai.
- **KHÔNG** case file (có trong DB nhưng không đưa vào prompt; test kiểm tra), **KHÔNG** ledger, **KHÔNG** nhắc lại ràng
  buộc ở cuối, **KHÔNG** reviewer. Output là văn bản thuần. `TURN_TEMPERATURE` = 0.5.
- Tin mời: `opening_first` chưa có tin user → thêm *"Mời bạn trình bày phần mở màn."* (theo spec). **Mở rộng cùng quy
  tắc:** hễ tin cuối không phải của learner thì thêm tin mời theo vòng. Việc này chỉ xảy ra ở AI con lượt 5 (tổng kết
  ngay sau phản bác của chính mình) → *"Mời bạn trình bày phần tổng kết."*. Lý do: chatbot cần một tin user để trả lời,
  và một số provider (Anthropic) coi tin `assistant` cuối cùng là prefill rồi viết tiếp nó. Tin mời mở màn được giữ lại
  trong lịch sử các lượt sau của AI pro, vì nó là một phần cuộc hội thoại đã diễn ra.
- Validator tối thiểu: không rỗng (rỗng → thử lại). `generator_version = turn_baseline_v1`.

**Script** `scripts/try_match.py` (LLM thật, cần DB dev + `alembic upgrade head`): tạo session → Case Planning → đủ 6 lượt
qua đúng tầng service của API; bài learner lấy từ `experiments/fixtures/match_M01_{pro,con}.json`. Đây là bài viết sẵn:
tiếng Việt tự nhiên, chất lượng trung bình như học sinh, 170–220 từ mỗi bài, phản bác nhắm vào luận điểm phổ biến của
phe kia. Bài **cố định**, không phản hồi nội dung cụ thể của AI. Script in transcript + mode + số từ / mục tiêu +
latency / token mỗi lượt AI, và ghi `experiments/matches/<timestamp>_<motion>_learner-<side>.json` để so với 3b.

**Chưa chạy LLM thật** (Khoa tự chạy script). Test: 26 test API (`tests/test_turns_api.py`) + 14 test format / prompt /
fixture (`tests/test_match_format.py`), LLM giả.

### 2.9. Giai đoạn 3b: bộ sinh lượt đầy đủ `turn_full_v1` (2026-09-30)

**Nguồn yêu cầu: 2 trận baseline** (Khoa chạy `try_match`, `turn_baseline_v1`, `openai/gpt-oss-120b`):
`experiments/matches/20260930-095631_M01_learner-pro.json` (AI con) và `…-095752_M01_learner-con.json` (AI pro).
Mình đã đối chiếu từng ý với transcript + `opponent_llm_calls` của DB dev:

| # | Vấn đề ở baseline (bằng chứng) | Thiết kế ở `turn_full_v1` |
|---|---|---|
| 1 | **Nhượng bộ bằng cách thu hẹp motion** — trận learner-con, AI pro lượt 3: *"mình không đề xuất cấm điện thoại suốt 24 giờ mà chỉ cấm trong thời gian học… Khi ra giờ giải lao, các em vẫn có thể sử dụng điện thoại"*; lượt 6: *"quan điểm 'cấm điện thoại trong giờ học' vẫn là lựa chọn hợp lý nhất"*. Đây gần như chính lập trường learner con ("cất điện thoại trong giờ học thay vì cấm cả ngày") | System: *"Cách hiểu kiến nghị của trận này là CỐ ĐỊNH: '{motion_reading}'"* (lấy từ case file) + ràng buộc *"KHÔNG thu hẹp, mở rộng hay định nghĩa lại kiến nghị"* |
| 2 | **AI con tự đề xuất giải pháp của phe kia** — trận learner-pro, lượt 4: *"mình đề xuất một hệ thống 'đặt khóa điện thoại' ở cổng vào: học sinh nộp điện thoại vào tủ khóa… chỉ được lấy lại sau giờ học"* — tức là cấm trong giờ ở trường, trùng ý learner pro "gửi điện thoại lúc vào trường" | Ràng buộc *"KHÔNG đề xuất như giải pháp của mình một phương án mà đội {learner} đã đưa ra hoặc gần giống…; thừa nhận tối đa một ý"* + system *"Phe của bạn không bao giờ thay đổi"* + ledger `ai_points` (*"không được mâu thuẫn"*) |
| 3 | **3 ca bịa bằng chứng**: *"nhiều vụ việc đã chứng minh"* (learner-pro lượt 2, bộ dò HIGH `nhieu_chu_the_da`), *"Nhiều nghiên cứu cho thấy…"* (learner-con lượt 1, HIGH `nghien_cuu_ket_luan`), *"Các lớp học hiện nay thường chỉ có 30‑40 phút cho mỗi môn"* (learner-pro lượt 4: con số khẳng định như sự thật, **bộ dò không bắt** — ca thứ 3 do mình xác định, cần Khoa xác nhận) | Ràng buộc: số chỉ trong tình huống 'Giả sử', không viện dẫn nghiên cứu / thống kê / 'nhiều nơi đã…'. Bộ dò **HIGH trên `speech_text` → retry có phản hồi**; câu có chữ số / "%" ngoài 'Giả sử' → **chỉ log** (`speech_checks.numbers_without_gia_su`) |
| 4 | **Quá dài**: 1,39–2,23 lần mục tiêu (6 lượt AI: 1,62 / 2,23 / 1,57 và 1,39 / 1,86 / 1,93; baseline chỉ có "Độ dài khoảng N từ" trong system) | Ràng buộc *"Độ dài speech_text: từ {0,8×} đến {1,2×} từ"* ở CUỐI prompt + **validator độ dài → retry có phản hồi** nêu số từ hiện tại và khoảng yêu cầu |
| 5 | **Xưng hô "em"** — gọi learner là "em" ở cả 2 trận (*"Chào em"*, *"Em ơi"*, *"Cảm ơn em đã lắng nghe"*), một lần tự xưng (*"Em mong mọi người… ủng hộ"*, learner-con lượt 6) | Ràng buộc *"Xưng 'mình', gọi người học là 'bạn'"*; regex đại từ "em" → **chỉ log** (`speech_checks.em_pronoun`, chấp nhận bắt nhầm "trẻ em") |
| 6 | **Tổng kết lặp lại** — liệt kê lại luận điểm thay vì cân nhắc (vd learner-con lượt 6 *"mình muốn tóm lại lại những gì đã diễn ra"* rồi kể lại "mất tập trung, gian lận, an toàn nội dung và sức khỏe") | Nhiệm vụ `closing`: *"nêu 2–3 điểm tranh chấp chính, với mỗi điểm so sánh vì sao phe bạn thắng; đáp lại điểm mạnh nhất… KHÔNG đưa lập luận mới, KHÔNG liệt kê lại toàn bộ luận điểm"* |
| 7 | **Chờ rate-limit tới 29s** trong 1 lượt (learner-con lượt 1: 429, chờ 28 920 ms; learner-pro lượt 2: 7 928 ms) | **MỘT lời gọi / lượt** (không tách pipeline phân tích → viết), giữ TPM thấp; retry chỉ khi output sai (tối đa 3). Chờ 429 vẫn tính trong `TURN_TOTAL_BUDGET_SECONDS` và được log (`rate_limit_wait_ms`) |

**Một lời gọi, output JSON** (structured output strict như Case Planning), thứ tự trường BẮT BUỘC:
`learner_claims → premises {explicit, implicit} → target_premise → ai_points (2–4) → speech_text`. Lý do: phân tích →
lập dàn ý → **mới viết**. Đây là bài học "diễn đạt lại trước khi kết luận" (mục 2.4l): model sinh theo thứ tự trường,
nên phần viết bài được "đặt điều kiện" trên phân tích đã có. Schema viết tay theo mode (giữ thứ tự `properties`):
`target_premise` là `string` ở `opening_reply` / `rebuttal`, là `null` ở `opening_first` / `closing`; `opening_first`
ép `learner_claims` / `premises` rỗng (`maxItems: 0`). Validator Pydantic vẫn chạy sau (provider khác không ép schema):
`opening_first` bị ép rỗng, `closing` bỏ `target_premise` (không tốn retry), lượt cần tấn công mà thiếu
`target_premise` → retry.

**Ledger** — dựng lại từ `opponent_turns` **mỗi lượt**, không có bảng riêng (`turn_service.build_ledger`): mọi
`learner_claims`, `ai_points`, `target_premise` của các lượt AI trước (lượt baseline — cột NULL — bị bỏ qua). Migration
`0009`: `opponent_turns.ai_points` (JSONB). Bài learner **cũ** không đưa lại nguyên văn: chỉ bài **mới** (sau lượt AI
gần nhất) ở dạng *"Đội {learner} vừa phát biểu ({vòng}):\n«…»"* (ngôi thứ ba). Bài cũ đi vào prompt qua
`learner_claims` đã trích — prompt không phình theo số lượt.

**Prompt** (`turn_full.build_full_prompt`): system = vai + phe + `motion_reading` cố định + phe learner; user = (a) case
(title, claim, reasoning + weighing) → (b) `ai_points` cũ → (c) `learner_claims` cũ + tiền đề đã tấn công → (d) bài
learner mới → (e) nhiệm vụ theo mode + quy tắc chọn `target_premise` theo độ khó (easy: tường minh bất kỳ; medium:
tường minh, nền tảng, chưa chứng minh đủ; hard: xét cả tiền đề ngầm + so mức tác động; không tấn công lại tiền đề cũ trừ
khi learner chưa đáp) + mô tả 5 trường JSON → (f) **khối ràng buộc nguyên văn, LUÔN ở cuối**. Mục (b), (c) bỏ qua khi
rỗng (spec chỉ ghi "bỏ qua nếu rỗng" cho (b); mình áp dụng cả cho (c) để không có tiêu đề trống). **Phản hồi retry chèn
TRƯỚC khối ràng buộc** (khác Case Planning, nơi phản hồi nối vào cuối), để khối ràng buộc vẫn là thứ cuối cùng model
đọc. Phản hồi không cộng dồn: mỗi lần chỉ mang phản hồi của lần trước.

**Validator** (retry CÓ phản hồi, `TURN_MAX_ATTEMPTS` = 3): sai JSON / schema; Groq từ chối schema → tự sửa tên
trường gõ sai ≤ 3 ký tự (top-level + `premises`), sửa được thì **không gọi lại LLM**; `speech_text` ngoài
[0,8; 1,2] × mục tiêu (opening 320–480, rebuttal 256–384, closing 208–312); bộ dò HIGH trên `speech_text`
(`vague_detector.detect_speech` — coi bài nói là khẳng định của AI, nên HIGH giữ nguyên mức). Có cả lỗi độ dài và HIGH
→ `failure_kind = banned_phrase` (như Case Planning), cả hai phản hồi đều được gửi. **Chỉ log**:
`opponent_llm_calls.vague_evidence` (mọi hit của bộ dò, lượt được chấp nhận chỉ còn LOW) và cột mới `speech_checks`
`{"numbers_without_gia_su": [câu], "em_pronoun": [câu]}`. Hết lượt thử → 502 (giống Case Planning).
`TURN_MAX_TOKENS` = 4000.

**Baseline giữ nguyên để so sánh:** `turn_baseline_v1` không đọc `TURN_MAX_TOKENS` / `TURN_MAX_ATTEMPTS` nữa mà cố định
giá trị 3a (3000 / 2), vì 3b đổi mặc định 2 biến này. Prompt, hội thoại, văn bản thuần: không đổi. `tests/test_turns_api.py`
(26 test 3a) ghim `turn_baseline_v1` và vẫn pass. Có thêm test baseline bỏ qua `TURN_MAX_ATTEMPTS=5` /
`TURN_MAX_TOKENS=9999`. Mặc định `TURN_GENERATOR_VERSION` → `turn_full_v1`.

**`try_match`**: `--generator turn_baseline_v1 | turn_full_v1`; file output
`<timestamp>_<motion>_learner-<side>_<generator>.json` (hai file 3a không có hậu tố = baseline). In thêm
`learner_claims`, `premises`, `target_premise`, `ai_points`, số lần thử lại + lý do (kể cả chờ 429), và phần chỉ log.

**Chưa chạy LLM thật.** Test: `tests/test_turn_full.py` (23 test, LLM giả) — thứ tự trường schema theo mode; prompt có
`motion_reading`, `ai_points` cũ, bài learner ngôi thứ ba, khối ràng buộc cuối (cả khi có phản hồi retry);
`opening_first` không có `target_premise`; `closing` cấm lập luận mới; retry khi độ dài sai / HIGH / schema; tự sửa tên
trường; ledger qua 3 lượt AI pro (1, 3, 6); baseline không bị ảnh hưởng.

### 2.10. 3b sửa lỗi: độ dài mềm, output bị cắt, mức suy luận, `turn_full_v2` (2026-09-30)

**Bằng chứng — trận 15:11** (`try-match-M01-pro-20260930-151150`, learner pro / AI con, `turn_full_v1`, DB dev; trận
dừng ở lượt 5 nên không có file trong `experiments/matches/`):
- **Lượt 5 (closing, mục tiêu 260, khoảng yêu cầu 208–312) thất bại vì độ dài hụt 1–2 từ:** lần thử 3 được **207** từ,
  lần 5 bị Groq 400 `json_validate_failed` với `failed_generation` **rỗng** (10,7s, không có usage), lần 7 được **206**
  từ → hết `TURN_MAX_ATTEMPTS` → 502 giữa trận. (Các lần 1, 2, 4, 6 là chờ 429.) Spec ghi "hụt 1–2 từ ×3 lần"; thực tế
  là **2 lần hụt độ dài + 1 lần output rỗng**, và lần rỗng bị ghi sai thành `schema_rejected`.
- **Lượt 4: `tokens_out` 3274 / 4000**, sát giới hạn: gpt-oss tính cả token suy luận vào `max_tokens`. Lần output
  rỗng ở lượt 5 nhiều khả năng là do suy luận dùng hết giới hạn trước khi kịp viết JSON.
- **Tổng chờ 429: 121,9s (> 2 phút) trong 6 lần** — 11,3 + 22,8 (lượt 2, 4) + 25,3 + 4,7 + 26,9 + 31,0s (lượt 5).
- **Bài nói đọc ra nhãn phân tích** — lượt 2: *"mình muốn chỉ ra rằng tiền đề 'Điện thoại làm học sinh mất tập trung'
  chưa được chứng minh đầy đủ"*, tức là đọc nguyên văn quy tắc chọn `target_premise` của độ khó medium.

**1. Độ dài là lỗi MỀM.** Prompt vẫn yêu cầu [0,8; 1,2] × mục tiêu (không đổi v1), nhưng khoảng **chấp nhận** là
[0,7; 1,25] × mục tiêu (opening 280–500, rebuttal 224–400, closing 182–325). Ngoài khoảng → thử lại có phản hồi **tối đa
1 lần**. Vẫn ngoài khoảng → **chấp nhận bản gần khoảng nhất** trong các lần thử hợp lệ (bằng nhau thì lấy bản sớm hơn),
ghi `speech_checks.length_soft_accept = {word_count, accept_min, accept_max}` vào lời gọi được chấp nhận, lời gọi đó
đổi thành `success`. Lượt **không bao giờ thất bại chỉ vì độ dài**: kể cả khi các lần sau gặp lỗi cứng rồi hết lượt thử,
bản hợp lệ-chỉ-sai-độ-dài vẫn được dùng. Lỗi cứng giữ nguyên: JSON / schema, bằng chứng HIGH (nếu cùng lúc sai độ dài
thì phản hồi nêu cả hai), output bị cắt. Với trận 15:11: 207 và 206 từ đều nằm trong [182; 325] nên được **chấp nhận
ngay**, không cần thử lại.

**2. Output rỗng / bị cắt → `truncated_max_tokens`** (không gộp vào `schema_rejected`), gồm 3 trường hợp: Groq 400
`json_validate_failed` với `failed_generation` **rỗng** (đúng ca lượt 5), response có `finish_reason = "length"`, và
nội dung rỗng. Đây là lỗi cứng: thử lại với phản hồi *"Output lần trước RỖNG hoặc bị CẮT… suy nghĩ ngắn gọn hơn, trả về
ĐỦ 5 trường"*. `error` ghi `finish_reason` và `tokens_out/max_tokens`. Riêng ca 400 thì provider không trả usage nên
`tokens_out` = NULL. Migration `0010`: `opponent_llm_calls.reasoning_tokens`
(`usage.completion_tokens_details.reasoning_tokens` với OpenAI / Groq, `thoughts_token_count` với Gemini; NULL nếu
provider không trả; **đã nằm trong** `tokens_out` của gpt-oss), `finish_reason` (Anthropic `max_tokens` / Gemini
`MAX_TOKENS` quy về `length`), `reasoning_effort` (giá trị ĐÃ gửi). Case Planning cũng ghi 3 cột này, nhưng **chưa** đổi
cách phân loại lỗi (xem việc còn treo).

**3. Mức suy luận.** Tài liệu Groq (kiểm tra 2026-09-30, `console.groq.com/docs/reasoning` + API reference):
`reasoning_effort` được hỗ trợ cho `openai/gpt-oss-20b` và `openai/gpt-oss-120b` với giá trị `low` / `medium` / `high`,
**mặc định `medium`**. Suy luận trả về ở trường `reasoning` riêng (`reasoning_format` không hỗ trợ với gpt-oss). Trang
model không nói rõ suy luận có tính vào `max_completion_tokens` hay không, nhưng số liệu thật cho thấy có (`tokens_out`
3274 cho bài nói ~300 từ). Đã thêm `CASE_PLAN_REASONING_EFFORT` (chỉ lời gọi planner, không áp dụng cho Stance
Reviewer) và `TURN_REASONING_EFFORT` (lượt nói: full và baseline). **Mặc định `None` = KHÔNG gửi tham số**, nên hành vi
giữ nguyên (Groq dùng `medium`). Chỉ `GroqClient` gửi tham số này; provider khác bỏ qua. `TURN_MAX_TOKENS` 4000 → **6000**.
`try_match --reasoning-effort low|medium|high` ghi đè cho các lượt nói, tên file có thêm hậu tố `_effort-<x>`. Lưu ý
`.env`: không đặt biến = không gửi; đặt `TURN_REASONING_EFFORT=` (rỗng) sẽ bị Pydantic từ chối, nên `.env.example` để
dạng comment.

**4. `turn_full_v2`** = v1 + đúng 1 dòng trong khối ràng buộc (sau dòng "bài NÓI"): *"Nói tự nhiên như một người tranh
luận; KHÔNG đọc ra các thuật ngữ phân tích như 'tiền đề', 'tiền đề ngầm' hay trích nguyên văn nhãn phân tích."*
v1 giữ nguyên (test so khối ràng buộc v2 bỏ dòng này thì bằng đúng v1). Mặc định `TURN_GENERATOR_VERSION` →
`turn_full_v2`. Các sửa ở mục 1–3 áp dụng cho **cả v1 và v2** (sửa lỗi, không phải thay đổi prompt).

**5. `try_match`.** Lượt AI thất bại → in lỗi + từng lần gọi của lượt đó (các lời gọi có `turn_id` NULL: failure_kind,
lỗi, `tokens_out`, reasoning, `finish_reason`, thời gian chờ 429), rồi **dừng gọn**, trả mã 1, và vẫn ghi file transcript
dở (`completed: false`, `failed_turn`). Session DB đóng bằng `async with`, engine dispose trong `finally` trước khi event
loop đóng: bản cũ `return` giữa `async for db in get_db()` và bỏ qua `dispose_engine()`. Cuối trận (kể cả khi dừng)
in **tổng thời gian chờ 429 của cả trận** (Case Planning + mọi lượt), đồng thời ghi vào file. Logic tách ra thành
`run_match()` để test với DB test + LLM giả.

Test mới: độ dài mềm (chọn bản gần nhất, chỉ 1 lần thử lại, trong khoảng chấp nhận thì không thử lại, giữ bản hợp lệ khi
các lần sau gặp lỗi cứng), 3 kiểu output bị cắt, schema_rejected có nội dung vẫn là `schema_rejected`, `reasoning_effort`
gửi / không gửi (Groq client, lượt nói, Case Planning — riêng planner), v2 so với v1, `try_match` dừng gọn + tổng chờ
429. **Chưa chạy LLM thật.**

### 2.11. Giai đoạn 3c: Stance Reviewer cho từng lượt + gọn token + mặc định `reasoning_effort = medium` (2026-09-30)

**So sánh 2 trận cùng fixture** (M01, learner pro / AI con, `turn_full_v2`, `TURN_MAX_TOKENS` 6000; Khoa chạy):
`experiments/matches/20260930-153606_…_effort-low.json` (session `…-153401`) và `…-155027_…_effort-medium.json`
(`…-154925`). Số liệu mỗi lượt AI (2 / 4 / 5): token tính tổng mọi lần gọi của lượt; `reasoning` là của lần được chấp nhận.

| | `low` (15:34) | `medium` (15:49) |
|---|---|---|
| **Phe của AI con** | **Lật phe cả 3 lượt**: bảo vệ việc CẤM (vd lượt 2: *"Nếu cấm điện thoại, lớp học sẽ trở lại môi trường tập trung cao độ"*) | Đúng phe ở lượt 2, 4. Lượt 5, ý P1 nghiêng về phe kia (*"trường có thể bố trí các điện thoại khẩn cấp cố định… không cần để mỗi học sinh mang điện thoại cá nhân"*) — đúng dạng lỗi mà reviewer cho lượt nói sẽ bắt |
| **Gán nhầm `learner_claims`** | Lượt 4: *"Điện thoại là công cụ học tập hỗ trợ"*, *"giúp liên lạc khẩn cấp"*… là luận điểm của **phe AI** (learner pro chỉ nhắc lại để phản bác) nhưng bị ghi là của learner | Đúng |
| Số lần thử lại (không tính 429) | 3 (lượt 2: độ dài; lượt 4: độ dài + `da_chung_minh`; lượt 5: `da_chung_minh`) | 0 |
| Số từ (mục tiêu 400 / 320 / 260) | 312 / 231 / 230 | 350 / 281 / 316 |
| `tokens_in` (tổng lượt) | 3382 / 6046 / 3883 | 1701 / 1914 / 1899 |
| `tokens_out` (tổng lượt) | 1845 / 2718 / 1698 | 1625 / 3851 / 2672 |
| `reasoning_tokens` (lần được chấp nhận) | 72 / 136 / 94 | 870 / 2948 / 1701 |
| Latency (ms) | 5470 / 8824 / 6802 | 4038 / 9231 / 6681 |
| Tổng chờ 429 cả trận | 93,0s (7 lần) | 29,6s (1 lần) |

Ở mức `low`, model gần như không suy luận (72–136 token). Nó lật phe cả trận và nhầm luận điểm của hai bên. Token còn
**tăng**, vì lần thử lại nhân `tokens_in` lên và làm tăng chờ 429. `medium` tốn token suy luận hơn nhưng không phải thử
lại lần nào. **Quyết định:** `TURN_REASONING_EFFORT = CASE_PLAN_REASONING_EFFORT = medium`, **gửi tường minh** (trước đây
không gửi = Groq tự dùng `medium`: hành vi giống nhau, nhưng giờ không còn phụ thuộc mặc định của provider và log ghi rõ
giá trị). Stance Reviewer không nhận tham số này. Hạn chế: mỗi mức chỉ có 1 trận.

**Stance Reviewer cho lượt nói** (`turn_full_v1` / `v2`; dùng lại `stance_reviewer.py`, **cố định v1** vì `ai_points`
không có phần "lý do" riêng cho v2 / v3):
- Input: motion + `ai_points` (mỗi ý là một "luận điểm" `P1..Pn`) + `speech_text` ở vị trí "phần kết luận / cân nhắc tổng
  thể của đội đó". Ngôi thứ ba ("Một đội tranh luận đưa ra…"). **Không truyền `ai_side`**: test cho cùng output ở hai
  phe thì reviewer nhận prompt giống hệt nhau.
- Code so với `ai_side` (`stance_reviewer.judge`):
  - `side_flip` → **retry TRUNG TÍNH**: prompt gốc, không phản hồi, bỏ cả phản hồi độ dài / lỗi trước đó (mục 2.4m),
    tính vào `TURN_MAX_ATTEMPTS`; lời gọi bị báo được đánh dấu `reviewer_detail.retry = side_flip_neutral_retry`.
  - `khong_ro` → chỉ log.
  - Reviewer lỗi (gọi thất bại / output sai) → thử lại reviewer 1 lần (không tính vào số lần thử), vẫn lỗi → `unclear`.
- **Hết lượt thử mà vẫn `side_flip` → lượt thất bại (502), không lưu speech.** Không bao giờ trả bài nói bị báo lật phe.
  Nếu trước đó có bản **đã qua reviewer** mà chỉ sai độ dài thì dùng bản đó (độ dài là lỗi mềm, mục 2.10).
  Reviewer chạy trên **mọi** output hợp lệ (trước khi xét độ dài), để bản dự phòng cũng đã được kiểm tra phe.
- Log như Case Planning: `reviewer_verdict` / `reviewer_detail` trên dòng `turn` và dòng `stance_review` riêng (model
  `STANCE_REVIEW_MODEL`, temperature 0, JSON schema). Lời gọi reviewer **dùng chung dãy `attempt`** với lời gọi sinh
  (vd 1 sinh, 2 review, 3 sinh, 4 review).
- **Baseline KHÔNG review** (giữ ngây thơ làm mốc): không gọi reviewer factory. `STANCE_REVIEW_ENABLED=false` → bỏ review.
- `try_match` in verdict mỗi lượt và mọi lần thử bị reject (`lan N (sinh|reviewer): side_flip · reviewer=side_flip
  ['P1', 'weighing']`). Khi lượt thất bại, danh sách lời gọi lấy theo id phát sinh trong lượt đó; bản trước lấy nhầm cả
  reviewer của Case Planning (cũng có `turn_id` NULL).

**Gọn token** (áp dụng cho cả v1 và v2, giống các sửa ở mục 2.10):
- **Không có bài learner mới** (AI con lượt 5, và `opening_first`): prompt ghi *"Không có bài nói mới của người học kể từ
  lượt trước của bạn."*; schema ép `learner_claims` / `premises` rỗng (`maxItems: 0`); code **ép rỗng bất kể model trả
  gì** và ghi `speech_checks.analysis_coerced = {trường: số mục bị bỏ}`. Bằng chứng: trận `medium` lượt 5 (không có bài
  mới) chép lại **9** `learner_claims` cũ.
- **Closing**: không yêu cầu phân tích tiền đề (prompt: *"để cả hai mảng rỗng (lượt tổng kết không phân tích tiền
  đề)"*, schema `premises` rỗng); code ép `premises` rỗng, `target_premise = null`. AI pro lượt 6 (có bài mới) vẫn trích
  `learner_claims`.
- Mục (c) ledger chỉ liệt kê `learner_claims` (và các tiền đề đã tấn công), **không** liệt kê lại `premises` cũ; đã đúng
  từ 3b, có thêm test giữ nguyên.

**Kiểm tra `da_chung_minh` trên bài nói** (chỉ đọc; session `…-153401`, các lần bị reject ở lượt 4, 5). Nguyên văn:
- Lượt 4 (lần gọi 4): *"Thêm vào đó, việc cho phép điện thoại trong lớp **đã chứng minh** làm học sinh mất tập trung, vì
  họ dễ dàng chuyển sang các ứng dụng giải trí và mạng xã hội, khiến thời gian học bị cắt giảm nghiêm trọng."*
- Lượt 5 (lần gọi 3): *"Bạn đã nêu rằng điện thoại giúp học sinh truy cập tài liệu nhanh, nhưng thực tế việc cho phép
  tự do sử dụng **đã chứng minh** làm học sinh mất tập trung và thời gian học bị cắt giảm nghiêm trọng."*

→ Cả hai đều **khẳng định điều gì đó "đã được chứng minh" mà không nêu nguồn**. Đây không phải cách nói tranh luận ("bạn
đã chứng minh…", "chưa chứng minh được…"), nên luật **bắt đúng**, và **không cần thu hẹp** dựa trên dữ liệu này. Đề xuất
(CHƯA làm, chờ Khoa quyết): bài nói xưng "mình" / "bạn", nên *"bạn đã chứng minh…"* hay *"mình đã chứng minh ở lượt
trước…"* sẽ bị HIGH nhầm, vì `exclude_subject` hiện chỉ loại "chúng tôi / chúng ta / phe / đội". Có thể thêm "bạn" /
"mình" vào danh sách chủ thể loại trừ, **chỉ trong `detect_speech`** (case file không xưng hô). *"chưa chứng minh"*
không khớp luật (luật cần "đã"). Cần gán nhãn hit trên bài nói trước khi đổi.

Test mới: `tests/test_turn_review.py` (14). **Chưa chạy LLM thật.**

### 2.12. Sửa sau trận 17:35 / 17:38: JSON "mảng tách", chờ 429 theo budget, lỗi mạng, `turn_full_v3` (2026-09-30)

**Bằng chứng** (DB dev; `turn_full_v2`, `medium`; Khoa chạy):
- **17:34** (`try-match-M01-pro-20260930-173447`): Case Planning chết ngay vì **1 lần `APIConnectionError: Connection
  error.`** (18,0s) — lỗi provider thì dừng ngay, chưa có retry. Trận kết thúc trước khi có lượt nói nào.
- **17:35** (`…-pro-20260930-173549`, learner pro / AI con, trận chạy hết 6 lượt): lượt 4 bị Groq 400
  `json_validate_failed` (*"'' does not validate with /type: expected object, but got array"*), sau đó là 429 (6,9s), rồi
  mới sinh lại được. Lượt 5 chờ 429 tổng 41,8s.
- **17:38** (`…-con-20260930-173838`, learner con / AI pro): **lượt 3 thất bại**. Thứ tự: `schema_rejected` (cũng dạng
  mảng) → 429 7,2s → 13,6s → 7,3s → `banned_phrase` (*"Nghiên cứu thực tế cho thấy"*) → 429 22,1s → **429 lần 5 bị trả
  thẳng lỗi vì hết `CASE_PLAN_RATE_LIMIT_RETRIES` = 4**, dù mới chờ 50,2s trong budget 120s → 502.

**Dạng lỗi "mảng tách"** (cả 2 ca, nguyên văn ở `tests/data/failed_generation_20260930-1735_turn4.json` và
`…-1738_turn3.json`). Model sinh một **mảng** thay vì một object:
`[{"learner_claims": […], "premises": {…}}, "target_premise", ":", "…", "…", "ai_points", ":", […], "speech_text", ":",
"Bạn nói rằng … thư viện", "nên học sinh …", …]`. Hai trường đầu vẫn đúng dạng; từ `target_premise` trở đi, **mỗi dấu
phẩy trong văn bản biến thành ranh giới chuỗi** (lượt 4 trận 17:35: `target_premise` bị tách thành 3 chuỗi, `speech_text`
thành 15 chuỗi; lượt 3 trận 17:38: `speech_text` thành 18 chuỗi).

**1. Chờ 429 của lượt nói chỉ giới hạn bởi budget.** `LLMCaller` bỏ giới hạn số vòng: 429 thì luôn chờ theo thời gian
provider yêu cầu (+ jitter) rồi gọi lại; chỉ `TURN_TOTAL_BUDGET_SECONDS` (**tăng 120 → 240**) chặn → 504. Lượt nói chỉ
thất bại vì 429 khi hết budget. Tổng thời gian chờ mỗi lượt được ghi vào cột mới `opponent_turns.rate_limit_wait_ms`
(migration `0011`) và log `Luot N (...): tong cho 429 Xs`; `try_match` in thêm `cho 429 Xs` ở dòng tiêu đề mỗi lượt AI.
Case Planning **giữ nguyên** `CASE_PLAN_RATE_LIMIT_RETRIES` (spec chỉ nói lượt nói; Case Planning đã có budget 240s riêng).

**2. Bộ sửa "mảng tách"** (`app/opponent/json_repair.py`, **tất định**, dùng chung cho lượt nói và Case Planning). Điều
kiện: output là mảng, phần tử đầu là object, phần sau là dãy `key, ":", giá trị…`, với key thuộc **danh sách trường đã
biết** (`TurnOutput` / `CaseFile`). Giá trị gồm nhiều chuỗi liên tiếp thì ghép bằng `", "` cho tới key kế tiếp hoặc hết
mảng; một giá trị đơn (vd mảng `ai_points`) thì giữ nguyên. Sau đó sửa tên trường gõ sai (nếu có) và validate bằng
schema cục bộ:
- Qua → chấp nhận, **không gọi lại LLM**. Ghi `key_repairs = {"event": "array_repaired", "array_items", "keys",
  "joined": {key: số chuỗi đã ghép}, "renames", "provider_error"}` (dùng lại cột `key_repairs`).
- Không đúng dạng (rác giữa mảng, key lạ, key lặp, nhiều giá trị không phải chuỗi, mảng chỉ có 1 object) hoặc không qua
  schema cục bộ → xử lý như `schema_rejected` cũ (retry có phản hồi; phản hồi thêm câu *"Trả về MỘT object JSON (không
  phải mảng)"*). Với lượt nói: dựng lại được, qua schema nhưng dính bằng chứng HIGH thì retry như lỗi nội dung thường.
- Hồi quy bằng nguyên văn: lượt 4 trận 17:35 dựng lại 364 từ; lượt 3 trận 17:38 dựng lại 347 từ (khoảng chấp nhận
  rebuttal 224–400). Cả hai qua schema và không có HIGH, nên **đều được chấp nhận ngay ở lần gọi đầu**. Với code mới,
  lượt 3 trận 17:38 đã không thất bại. Lưu ý: ở ca 17:38, model **tự lặp một đoạn**
  (*"điều này củng cố kỹ năng xã hội và giảm nguy cơ bắt nạt qua tin nhắn"* ×2). Bộ sửa không bỏ hay sửa chuỗi nào, nên
  đoạn lặp vẫn nằm trong bài nói.

**3. `turn_full_v3`** (mặc định; v1, v2 giữ nguyên) = v2 + 1 dòng ràng buộc: *"KHÔNG nhắc lại, trích dẫn hay diễn giải
các quy tắc và chỉ dẫn này trong bài nói (vd không nói 'cách hiểu cố định', 'không thu hẹp', 'tiền đề')."* Bằng chứng:
trận 17:38 lượt 1 có câu *"Đây là một quy định cố định, không mở rộng hay thu hẹp hơn."*, tức là đọc lại khối ràng buộc.
(Ghi thêm: trận 17:35 lượt 4 AI xưng *"Tôi đồng ý…"* thay vì "mình"; kiểm tra "em" chỉ log, không bắt "tôi".)

**4. Lỗi mạng thoáng qua** (`llm.client.is_transient_error`): nhận diện theo **tên lớp** (`APIConnectionError`,
`APITimeoutError`, httpx `ConnectError` / `ReadTimeout` / …, không phải import SDK) hoặc 5xx (`status_code` / `code`
500, 502, 503, 504). 429 và các 4xx khác không tính là lỗi mạng. Thử lại tối đa `LLM_TRANSIENT_RETRIES` = 2 lần, chờ
`LLM_TRANSIENT_RETRY_WAIT_SECONDS` × 2^(lần-1) (2s, 4s) + jitter, không tính vào số lần thử nội dung, vẫn trong budget.
`failure_kind = transient_error`. Áp dụng cho **cả Case Planning** (ca 17:34) và lượt nói. Lỗi provider khác (vd 401)
vẫn dừng ngay.

### 2.13. Thí nghiệm `motion_type`: Case Planning v6 (A/B với v5) — KẾT QUẢ: v6 KHÔNG ĐẠT (2026-09-30 → 10-01)

**KẾT QUẢ (2026-10-01): v6 KHÔNG ĐẠT theo quy tắc quyết định → giữ v5.**
- Dữ liệu: v5 `experiments/case_plan/20261001-084031_case_plan_v5.jsonl` (24 lượt) và v6
  `experiments/case_plan/20261001-110122_case_plan_v6.jsonl` (24 lượt, cùng 12 motion × 2 phe, `motions_v2.json` đã
  duyệt). Hai file v6 dở dang trước đó (`090040`, `092013`, nhiều `budget_exceeded`, mục 2.14) đã không còn trong thư
  mục; kết quả dưới đây chỉ dùng `110122`.
- **Điều kiện 1a (thành công) TRƯỢT:** v6 **22/24** vs v5 **24/24**, chênh 2 lượt > ngưỡng 1. Hai lượt thất bại là
  V1 pro medium và V4 pro medium (`invalid_output`: hết lượt thử vì `side_flip` ở cả 3 lần, lần thử 1, 3, 5). Vì điều
  kiện 1 không đạt, không cần xét điều kiện 2.
- **7 lần gắn cờ `side_flip` ở v6** (V1 pro ×3, V1 con ×1, V4 pro ×3) đã được **đọc tay: đều lật phe THẬT** (reviewer
  đúng cả 7).
- **Nguyên nhân:** cách hiểu chuẩn của motion **value** viết TRUNG LẬP (vd V1: *"Cân nhắc tổng thể tác hại và lợi ích
  của mạng xã hội đối với người từ 15 đến 24 tuổi."*), làm **mất chiều khẳng định** của kiến nghị (*"gây hại nhiều hơn có
  lợi"*). Model bảo vệ chính việc "cân nhắc". V1 pro, lần thử 5, weighing: *"…việc xem xét cả tác hại và lợi ích cho phép
  xây dựng các biện pháp giáo dục… do đó, phe Đề xuất thắng vì đưa ra hướng tiếp cận cân bằng, thực tiễn và phù hợp với
  bối cảnh Việt Nam."* Các claim cùng lần thử: *"Cân nhắc tổng thể giúp tránh việc đưa ra các quy định quá nghiêm
  ngặt…"*, *"Đánh giá tổng thể giúp công chúng có cái nhìn cân bằng…"*. Reviewer: A1–A3 phản đối, weighing ủng hộ →
  `side_flip`.
- **Bỏ qua gán nhãn Q2 cho v6** (kết luận đã rõ từ điều kiện 1a). Bài học: "cách hiểu chuẩn" cho kiến nghị giá trị phải
  giữ **chiều khẳng định** của từng phe, chứ không chỉ mô tả phạm vi → thí nghiệm v6b (mục 2.15).
- Ghi thêm cho nhánh v5 (mục 2.14): V3 con easy là lật phe thật lọt vào case file cuối (reviewer lỗi).

**Quy tắc quyết định** — nguyên văn Khoa gửi, ghi TRƯỚC khi có dữ liệu:

> QUY TẮC QUYẾT ĐỊNH (chốt ngày 30/09/2026, trước khi có dữ liệu)
> Nhận case_plan_v6 (danh mục motion có motion_type + motion_reading) nếu ĐỦ CẢ HAI:
> 1. Không tệ hơn v5 — trên 24 lượt mỗi nhánh:
>    - Thành công: v6 thấp hơn v5 không quá 1 lượt.
>    - Lật phe THẬT (reviewer gắn cờ + người xác nhận): v6 nhiều hơn v5 không quá 1 ca.
>    - Bằng chứng mơ hồ mức HIGH trong case file cuối: v6 nhiều hơn v5 không quá 1 ca.
> 2. Tốt hơn rõ rệt — ít nhất MỘT trong hai:
>    - Tỷ lệ "đúng cấu trúc loại" (Q2, gán nhãn mù) của v6 cao hơn v5 từ 20 điểm phần trăm trở lên, tính trên cả 24 mẫu.
>    - Lật phe thật ở loại comparative: v6 ít hơn v5 (và v5 có ít nhất 1 ca).
> Không đạt → giữ v5; kết quả vẫn được báo cáo như một phát hiện.
> Q1 (độ lệch cách hiểu) chỉ đo trên nhánh v5 và chỉ dùng để mô tả, không tham gia quyết định.
> Hạn chế ghi nhận: mẫu nhỏ (24/nhánh, 8/loại), một người gán nhãn, Q1 không mù.

**Sửa đổi quy tắc** — nguyên văn Khoa gửi, cũng TRƯỚC khi có dữ liệu (quy tắc gốc ở trên giữ nguyên, không xoá):

> SỬA ĐỔI QUY TẮC (30/09/2026, TRƯỚC khi có dữ liệu) — lý do: validator đã loại mọi case file có HIGH, nên "HIGH trong
> case file cuối" luôn bằng 0 ở cả hai nhánh và không phân biệt được gì.
> Thay điều kiện 1c bằng: "Số lần thử bị chặn vì bằng chứng HIGH (tính trên mọi lần thử của 24 lượt): v6 nhiều hơn v5
> không quá 2 lần."
> Các điều kiện khác giữ nguyên.

→ Điều kiện **đang áp dụng**: 1a (thành công), 1b (lật phe thật), **1c SỬA ĐỔI** (lần thử bị chặn vì HIGH, dung sai 2),
2 (Q2 +20 điểm % hoặc lật phe thật comparative).

Ghi chú áp dụng (của mình, không thay đổi quy tắc):
- "24 lượt mỗi nhánh" = 12 motion × 2 phe của `motions_v2.json`, mỗi nhánh 1 batch.
- "Lật phe THẬT" cần người xác nhận: số lần reviewer báo `side_flip` trong batch / bảng so sánh chỉ là số **gắn cờ**,
  chưa phải số ca thật. Xác nhận bằng `label_stance` (gán nhãn mù phe) trên đúng các lần thử bị gắn cờ, hoặc
  `replay_stance_review --from-batch … --only-flagged`.
- ~~1c gốc "HIGH trong case file cuối"~~ — đã thay bằng sửa đổi ở trên (lý do: luôn bằng 0 ở cả hai nhánh).
- 1c sửa đổi, "số lần thử bị chặn vì bằng chứng HIGH": đọc dòng **"Reject HIGH (lần thử)"** / *"Bi reject do cum cam /
  bang chung mo ho HIGH (lan thu)"* của `compare_case_plan_batches` (số lần thử `case_plan` có `failure_kind =
  banned_phrase`, trên mọi lần thử của mọi lượt, kể cả lượt cuối cùng thất bại). **Có thể đếm THIẾU:** nếu Groq từ chối
  schema, code tự sửa được (tên trường gõ sai / "mảng tách", mục 2.12) nhưng bản đã sửa lại dính HIGH, thì lần thử đó
  được ghi `failure_kind = schema_rejected` (nội dung HIGH chỉ nằm trong `retry_feedback`: *"… có lời viện dẫn bằng
  chứng mơ hồ …"*). Để đếm đủ: cộng thêm các lần thử `schema_rejected` có `retry_feedback` chứa câu đó — đếm tay, hoặc
  bổ sung vào script so sánh (CHƯA làm, vì yêu cầu lần này chỉ sửa dev log). Cả hai nhánh bị đếm cùng một cách.

**Giả thuyết đang kiểm tra** (từ mục 2.12, trận 17:38): model tự diễn giải kiến nghị, và phe Đề xuất có thể thu hẹp
motion trùng với phương án của phe Phản đối. Nếu cách hiểu **được duyệt trước** và có **module theo loại kiến nghị**
thì case file bám cách hiểu chuẩn hơn và có cấu trúc đúng loại (chính sách: có luận điểm thực thi; so sánh: vừa bảo vệ
vừa đánh lựa chọn kia; giá trị: tiêu chí cân nhắc rõ).

**API + DB** (không đổi hành vi cũ):
- `POST /opponent/sessions` nhận thêm 2 trường **tuỳ chọn**: `motion_type` (`policy` / `comparative` / `value`) và
  `motion_reading` (text, NFC + strip; rỗng = không gửi). Thiếu cả hai → hành vi cũ. Chỉ có một trong hai → **400**.
  Giá trị `motion_type` lạ → 422 (Pydantic).
- Migration `0012`: `opponent_sessions.motion_type` (enum `motion_type`, nullable), `motion_reading_provided` (text,
  nullable). `GET /opponent/sessions/{id}` trả cả hai.
- Idempotent: hai trường nằm trong phần so sánh "cùng id, khác dữ liệu → 409" (kể cả lần đầu gửi còn lần sau bỏ).

**`case_plan_v6`** (`app/opponent/prompts/case_plan_v6.py`; mặc định **vẫn** `case_plan_v5`, v5 không đổi một chữ):
- Chỉ dùng khi `CASE_PLAN_PROMPT_VERSION=case_plan_v6` **và** session có cả hai trường. Cấu hình v6 mà session thiếu
  → tự dùng v5, và `prompt_version` ghi đúng bản đã dùng. Cấu hình v5 thì bỏ qua hai trường này dù Main Flow có gửi
  (A/B đúng nghĩa: nhánh v5 không thấy cách hiểu chuẩn).
- So với v5:
  - **Quy tắc 1** (SIDE_RULE, phần "tự diễn giải kiến nghị") được thay bằng câu nguyên văn *"Cách hiểu kiến nghị
    trong trận này (đã được ban tổ chức duyệt, dùng nguyên văn, không diễn giải lại): '{motion_reading}'."*
  - Lưu ý phe Đề xuất: SIDE_RULE của v5 có 3 câu, chỉ câu đầu là diễn giải (*"Định nghĩa kiến nghị một cách công
    bằng…"*). Hai câu sau (*"KHÔNG mô tả sai hiện trạng…"*, *"Nếu không chắc về một chi tiết thực tế, đừng nêu nó."*)
    **được giữ** và nối sau câu cách hiểu, để v6 chỉ khác v5 đúng phần diễn giải. Phe Phản đối: SIDE_RULE toàn bộ là
    diễn giải (*"Chấp nhận cách hiểu phổ biến… KHÔNG thêm ngoại lệ…"*) nên bị thay hết.
  - **Quy tắc 2 mới** = đúng 1 module theo loại (nguyên văn spec). Quy tắc 2..13 của v5 → 3..14, nguyên văn.
  - Mẫu JSON chỉ đổi mô tả `motion_reading` thành *"<chép NGUYÊN VĂN cách hiểu kiến nghị đã cho ở quy tắc 1>"*.
    CaseFile, validator, số luận điểm, JSON schema, Stance Reviewer: giống v5.
  - Test kiểm tra điều này theo từng quy tắc, cho 3 loại × 2 phe.
- **Ghi đè**: case file được chấp nhận luôn có `motion_reading` = bản được gửi. Model trả khác thì bản của model được ghi
  vào `key_repairs.motion_reading_overridden.model` của lần thử được chấp nhận (dùng lại cột "sửa tất định của code",
  gộp với `array_repaired` nếu có).
- **Không gộp sửa lỗi nào khác vào v6.**

**Bộ motion** `experiments/motions_v2.json`: 12 motion, 4 policy (P1–P4), 4 comparative (C1–C4), 4 value (V1–V4). Mỗi
motion có `id`, `text`, `motion_type`, `motion_reading` (nguyên văn spec) và **`reading_status: "draft"`**. Khoa duyệt,
sửa và đổi trạng thái trước khi chạy; batch **từ chối chạy** khi còn `draft` (trừ `--allow-draft`), cho cả v5 lẫn v6,
để hai nhánh chạy trên cùng bộ đã duyệt.

**Batch runner**: `--motions experiments/motions_v2.json --prompt-version v5|v6`. `load_motions` đọc được cả v1
(`motion`) lẫn v2 (`text`). v5 không gửi type/reading; v6 gửi cả hai (và từ chối nếu motion nào thiếu). **Mọi dòng
JSONL** ghi `motion_type` và `motion_reading` (chuẩn, lấy từ file motion, chỉ để phân tích) cùng `motion_reading_sent`
(bản ĐÃ gửi cho LLM: v6 = reading, v5 = null). **So sánh**: `compare_case_plan_batches --v5 … --v6 …` có thêm bảng tách
theo `motion_type` (thành công, lần chạy có side_flip, reject HIGH, `content_retries` tb, `tokens_in` tb / lần chạy =
tổng mọi lời gọi, latency tb). Bảng chính có thêm dòng `tokens_in`.

**Gán nhãn** `scripts/label_case_structure.py` — **hai lượt**, hai file CSV riêng (mỗi lượt chạy tiếp được):
- **Lượt 1 (mặc định) — Q2, MÙ, mọi mẫu** (case file cuối của các lần chạy `ready` ở cả v5 lẫn v6), xáo trộn ổn định
  theo `--seed` (sắp theo `sample_id` trước khi xáo). Hiện: kiến nghị, loại, cách hiểu CHUẨN (`motions_v2.json`, làm
  ngữ cảnh), claim + reasoning từng luận điểm, weighing. **Không** hiện `motion_reading` của case file, kể cả bản model
  tự viết (v6 chép nguyên văn cách hiểu chuẩn, hiện ra là lộ nhánh), cũng như prompt_version, tên file, phe, độ khó,
  reviewer. Q2 (y / n) theo loại: policy *"Có ít nhất một luận điểm về thực thi/khả thi?"*, comparative *"Vừa bảo vệ
  lựa chọn của mình VỪA đánh lựa chọn kia?"*, value *"Phần cân nhắc có tiêu chí rõ ràng?"*. Mẫu không có
  `motion_type` bị bỏ qua. Lưu `experiments/labels/case_structure_q2.csv`.
- **Lượt 2 (`--q1`) — Q1, KHÔNG MÙ, CHỈ mẫu v5, chỉ dùng để MÔ TẢ** (không tham gia quy tắc quyết định): hiện
  `motion_reading` model viết cạnh cách hiểu chuẩn; g / h / r / k (giống / hẹp hơn / rộng hơn / khác hẳn). Lượt này
  chỉ lấy mẫu v5 nên người gán **biết** đang xem nhánh v5. Lưu `experiments/labels/case_structure_q1.csv`.
- `--report`: Q2 theo nhánh × loại và tổng (nhánh đọc lại từ file nguồn); Q1 chỉ cho v5 (dòng Q1 của mẫu không phải v5
  bị loại). Nên làm lượt 1 **trước** lượt 2, để khi gán Q2 chưa từng nhìn cách hiểu model viết.

Test: `tests/test_motion_type_v6.py` (25). **Chưa chạy LLM thật; chưa có dữ liệu.**

### 2.14. Stance check FAIL-CLOSED: reviewer lỗi thì KHÔNG chấp nhận output (2026-10-01)

**Bằng chứng — lật phe thật lọt vào case file cuối của nhánh v5** (batch `experiments/case_plan/20261001-084031_case_plan_v5.jsonl`,
V3 *"Trí tuệ nhân tạo mang lại nhiều lợi ích hơn tác hại cho học sinh"*, AI **con**, easy, run 21):
- Lần thử 1 sinh case file hợp lệ. Reviewer gọi 2 lần, **cả 2 lần** Groq trả 400 `json_validate_failed` với
  `failed_generation` **rỗng** (3,3s và 3,0s, không có usage), bị ghi là `schema_rejected`. Hết 2 lần thử reviewer →
  `reviewer_failure()` → verdict `unclear` → **case file được chấp nhận**, `final_status = ready`.
- Đọc tay: A1 *"AI giúp học sinh học hiệu quả hơn…"*, A2 *"AI mang lại cơ hội học tập chất lượng cho học sinh ở mọi
  vùng miền…"*. Weighing tự nói *"…do đó phe phản đối thắng khi nhấn mạnh rằng AI mang lại nhiều lợi ích hơn tác hại
  cho học sinh"*. **Cả 2 claim lẫn weighing đều bảo vệ phe Đề xuất: lật phe toàn bộ**, nhưng lọt vì reviewer không
  chạy được.
- Nguyên tắc cũ "reviewer lỗi → unclear, không chặn" (mục 2.4e) là **fail-open**: đúng khi muốn tránh làm hỏng Case
  Planning vì reviewer, nhưng sai về an toàn. Một output **chưa được kiểm tra phe** bị coi như output đã kiểm tra.

**Quy luật lật phe gần đây** (Khoa ghi nhận): các ca lật phe đều ở **phe Phản đối (con) của kiến nghị dạng so sánh /
phủ định**, gồm M01 ×2, V3, V4. Đối chiếu dữ liệu mình có:
- **M01** *"Nên cấm…"* (kiến nghị cấm, phe con là "không nên cấm"):
  - trận 15:34 (`reasoning_effort = low`) lật cả 3 lượt nói (mục 2.11);
  - batch v6 `20261001-090040` P1 (cùng câu kiến nghị) con medium bị gắn cờ `side_flip` ở lần thử 1 và 3 — **chưa có
    người xác nhận**.
- **V3** *"…nhiều lợi ích hơn tác hại…"*: ca trên, **người xác nhận** lật phe thật.
- **V4** *"Game online gây hại nhiều hơn có lợi…"*: batch v5 trên, con hard bị gắn cờ `side_flip` ở lần thử 1, lần thử
  sau qua reviewer — **chưa có người xác nhận** lần gắn cờ là thật.
- Giả thuyết: phe con của "A hơn B" phải bảo vệ "A **không** hơn B", tức là chứng minh **mặt kia**. Model dễ trượt về
  việc kể lợi ích / tác hại theo đúng chiều chữ trong kiến nghị. Liên quan việc còn treo về `motion_reading` (mục 2.12)
  và thí nghiệm `motion_type` (mục 2.13).

**1. Fail-closed** (Case Planning **và** lượt nói `turn_full_v*`): reviewer không trả được verdict sau
`stance_reviewer.MAX_CALLS` (2) lần gọi (lỗi gọi, output sai, output rỗng) → **KHÔNG chấp nhận output**. Xử lý như
`side_flip`: dòng `case_plan` / `turn` nhận `failure_kind = "reviewer_unavailable"`, sinh lại **trung tính** (prompt
gốc, không phản hồi; `reviewer_detail.retry = "reviewer_unavailable_neutral_retry"`), **tính vào** `CASE_PLAN_MAX_ATTEMPTS`
/ `TURN_MAX_ATTEMPTS`. Hết lượt → thất bại (Case Planning 502, phiên `failed`; lượt nói 502, không lưu speech). Lượt
nói: nếu trước đó có bản **đã qua reviewer** mà chỉ sai độ dài thì vẫn dùng bản đó (mục 2.10). Reviewer lỗi vẫn được
ghi `reviewer_verdict = unclear` + `reviewer_detail.reviewer_error` (giữ định dạng cột cũ). Code phân biệt bằng
`stance_reviewer.is_reviewer_failure(detail)`. **Verdict `khong_ro` do reviewer trả THẬT vẫn giữ hành vi cũ**: đó là
phán đoán, không phải lỗi, nên chỉ log và chấp nhận. `content_retries` của batch đếm cả retry kiểu mới.

**2. Reviewer output rỗng → `truncated_max_tokens`** (không còn là `schema_rejected`):
- Case Planning: Groq 400 `json_validate_failed` với `failed_generation` rỗng, **chỉ ở lời gọi reviewer**. Planner vẫn
  theo luồng `schema_rejected` cũ, vì đổi sẽ làm lệch chỉ số so sánh batch (việc còn treo 2.10). Thêm: output parse lỗi
  mà `finish_reason = "length"` hoặc rỗng.
- Lượt nói: `LLMCaller` đã làm điều này từ mục 2.10.
- Token: ca 400 không có usage → `tokens_*` = NULL; trường hợp `finish_reason = "length"` có `tokens_out` /
  `reasoning_tokens`.
- **`STANCE_REVIEW_MAX_TOKENS` hiện = 2000** (mục 2.4l; không đổi). `tokens_out` reviewer thành công hôm nay: tối đa
  **1277** (v6 `090040`), 1120 (v5 `084031`), trung bình 759–952. Hai lần rỗng của V3 không đo được token (400). Mức
  2000 còn dư so với các lần thành công, nhưng nếu output rỗng là do suy luận dùng hết giới hạn thì 2000 có thể vẫn
  thiếu ở ca khó. Cân nhắc tăng lên 3000 nếu `truncated_max_tokens` của reviewer lặp lại (**chưa đổi**, chờ Khoa).

**3. Script so sánh batch**: dòng mới *"Case file cuoi KHONG duoc reviewer cham pass (unclear/loi)"* (trên cấu hình
chung), kèm **danh sách từng ca để đọc tay** lấy từ **mọi** lần chạy của từng nhánh (không chỉ cấu hình chung, để không
sót ca chỉ có ở một nhánh). Mỗi ca ghi lý do: reviewer LỖI / `khong_ro: [id]` / không review. Chạy chỉ đọc trên 3 batch
hôm nay: v5 = 1 (V3 con easy, reviewer lỗi), v6 = 0.

*Ghi chú ngoài phạm vi:* 2 file v6 hôm nay (`090040`, `092013`) có **8/13** lượt `budget_exceeded` (10 lần chờ 429 trên
cấu hình chung). Nhánh v6 chưa đủ 24 lượt để áp quy tắc quyết định (mục 2.13); cần xem nguyên nhân (rate limit / budget
240s) trước khi chạy lại.

Test: `tests/test_stance_reviewer.py` (Case Planning: lỗi reviewer → retry trung tính → chấp nhận lần sau; hết lượt →
thất bại; output rỗng → `truncated_max_tokens`; `khong_ro` thật vẫn chấp nhận; v3), `tests/test_turn_review.py` (lượt
nói: retry trung tính, hết lượt → 502 không lưu speech, output rỗng), `tests/test_compare_batches.py` (đếm + liệt kê,
kể cả ca chỉ có ở một nhánh). **Chưa chạy LLM thật.**

### 2.15. Thí nghiệm v6b: gánh nặng chứng minh (A/B với v5) — KẾT QUẢ: v6b KHÔNG ĐƯỢC NHẬN, giữ v5 (2026-10-01)

**KẾT QUẢ (2026-10-01)** — v6b `experiments/case_plan/20261001-112324_case_plan_v6b.jsonl` (24 lượt, `motions_v3.json`) vs
v5 `20261001-084031_case_plan_v5.jsonl` (24 lượt), cùng 24 cấu hình (motion, phe, độ khó):

| Điều kiện (quy tắc 2.13 + sửa đổi 1c, áp cho v6b) | v5 | v6b | Ngưỡng | Kết quả |
|---|---|---|---|---|
| 1a Thành công | 24/24 | 23/24 (V4 con hard `invalid_output`) | v6b thấp hơn ≤ 1 | **ĐẠT** (−1) |
| 1b Lật phe THẬT (gắn cờ + người xác nhận) | 2 (V3 con easy — lọt vào case file cuối, mục 2.14; V4 con hard — gắn cờ lần thử 1) | 0 (không có lần gắn cờ nào) | v6b nhiều hơn ≤ 1 | **ĐẠT** |
| 1c (sửa đổi) Lần thử bị chặn vì HIGH | 1 | 2 | v6b nhiều hơn ≤ 2 | **ĐẠT** (+1) |
| 2 Q2 "đúng cấu trúc loại" (mù) cao hơn ≥ 20 điểm % | — | — | — | **CHỜ gán nhãn Q2** |
| 2 (lựa chọn khác) Lật phe thật loại comparative ít hơn, v5 ≥ 1 ca | 0 ca comparative | 0 | — | Không áp dụng được (v5 không có ca comparative) → điều kiện 2 **chỉ còn phụ thuộc Q2** |

1c: không có lần thử `schema_rejected` nào mà `retry_feedback` chứa câu bằng chứng mơ hồ, ở cả hai nhánh, nên không có
ca đếm thiếu (ghi chú 2.13).

**Q2 (gán nhãn MÙ, Khoa, `label_case_structure` lượt 1):** v5 **24/24 (100%)**, v6b **23/23 (100%)** (V4 con hard không
có case file cuối). Chênh 0 điểm %, dưới ngưỡng +20 → **điều kiện 2 KHÔNG ĐẠT** (lựa chọn comparative không áp dụng được)
→ **v6b KHÔNG được nhận, giữ v5.**
- **Diễn giải:** **hiệu ứng trần**. v5 đã viết đúng cấu trúc loại ở mọi mẫu, nên không còn chỗ để v6b tốt hơn; hoặc câu
  hỏi Q2 quá dễ đạt (y / n thô, không đo chất lượng). **Không có bằng chứng** cho module theo `motion_type` (cả v6 lẫn
  v6b). Bài học cho các thí nghiệm sau: chọn chỉ số còn dư địa ở nhánh đối chứng.
- **Phát hiện phụ** (ngoài quy tắc, quan sát sau dữ liệu): lật phe 0 lượt ở v6b vs 2 lượt ở v5 → **kiểm chứng bằng thí
  nghiệm v7 (mục 2.16)**, chỉ tách riêng khối gánh nặng chứng minh.

**Phát hiện phụ — QUAN SÁT SAU KHI CÓ DỮ LIỆU, KHÔNG thuộc quy tắc đã chốt:** lật phe thật **0 (v6b) vs 2 (v5)**, cả 2
ca v5 đều là phe con của kiến nghị dạng value "A nhiều hơn B" (V3, V4; quy luật mục 2.14). Đây là gợi ý ủng hộ giả
thuyết gánh nặng chứng minh. Nhưng quy tắc chỉ dùng lật phe cho "không tệ hơn" (1b) và cho loại comparative (điều kiện
2), nên con số này **không được dùng để nhận v6b**. Mẫu cũng nhỏ (2 ca).

**Quan sát thêm (sau dữ liệu, chỉ đọc, chưa sửa):**
- **`key_repairs` trong v6b không có lần sửa tên trường nào.** Cả 23 mục `key_repairs` (1 / lượt `ready`) đều là log
  `motion_reading_overridden` (code ghi đè `motion_reading` = burden phe AI), không phải sửa tên trường. Không có
  `key_repaired` hay `array_repaired`. Chỉ số *"Tu sua ten truong, khong goi lai LLM" = 23* trong summary của batch là
  **SAI NGHĨA**: `summarize()` đếm mọi lần thử có `key_repairs` khác rỗng, và log ghi đè dùng chung cột này (thiết kế
  của mục 2.13). v5: 0 `key_repairs`; v6 (`110122`): 0. Ở v6, 22/22 lượt `ready` model chép ĐÚNG nguyên văn cách hiểu, nên không cần ghi đè, còn v6b thì 23/23 lượt phải ghi đè.
  Model v6b ghi `motion_reading` = **nguyên văn câu kiến nghị** ở **23/23** lượt. Nó chép dòng đầu của khối (*"Kiến
  nghị: '…'"*) chứ không phải câu gánh nặng của phe mình, dù mẫu JSON yêu cầu *"chép NGUYÊN VĂN điều phe bạn phải chứng
  minh"*. Vô hại vì code ghi đè, nhưng cho thấy model không đọc kỹ mô tả trường.
- **8 lần Groq từ chối schema ở v6b, toàn bộ ở lời gọi PLANNER** (P3 pro, P4 con ×2, C1 pro, C1 con, C3 con, V4 con
  ×2). So sánh: v5 có 2 `schema_rejected`, **cả hai là lời gọi reviewer** (V3 con, output rỗng, mục 2.14); v6 có 1,
  **cũng là reviewer** (V4 con, rỗng). Tính riêng planner: **v5 0/27, v6 0/31, v6b 8/33** lần gọi `case_plan`. 7/8 được
  cứu ở lần thử sau. V4 con hard thất bại (schema → HIGH → schema), đây là lượt duy nhất v6b trượt ở điều kiện 1a.
  **Không liên quan `key_repairs`**: không lần nào sửa tên trường được, và bộ sửa "mảng tách" (mục 2.12) chỉ xử lý mảng
  ở **cấp ngoài cùng**, còn ở đây cấp ngoài cùng vẫn là object.
  - Cơ chế (đọc `failed_generation`): **biến thể "mảng tách" lồng trong `arguments`**. Phần tử đầu là object đúng, từ
    phần tử thứ hai trở đi hỏng:
    - (a) chèn **chuỗi rỗng `""`** giữa các object (`[A1, "", A2, "", A3]`, #1 P3 pro; #3 P4 con lần 2) → *"maxItems:
      got 5 / 4, want 3"*;
    - (b) các phần tử sau là **object bị tuần tự hoá thành chuỗi JSON** (`"{ \"id\": \"A2\", …"`, #2 P4 con lần 1, cả
      trong `anticipated_opponent_arguments`) → *"expected object, but got string"*;
    - (c) **phần còn lại của tài liệu bị nuốt vào trong `arguments`**: hoặc 1 chuỗi duy nhất chứa A2, A3,
      `anticipated_opponent_arguments`, `weighing` (#4 C1 pro, #7 V4 con lần 1; `json.loads` lỗi "Extra data"), hoặc dãy
      `"anticipated_opponent_arguments", ":", […], "weighing", ":", "…", "…"` (weighing bị tách ở mỗi dấu phẩy, đúng
      dạng mục 2.12) nằm trong mảng `arguments` (#5 C1 con, #6 C3 con, #8 V4 con lần 3) → *"missing properties:
      'anticipated_opponent_arguments', 'weighing'"*.

**Đề xuất nguyên nhân + cách sửa (CHƯA làm, chờ Khoa quyết):**
- *Nguyên nhân (giả thuyết, chưa chứng minh):* đây là cùng họ lỗi "tuần tự hoá rồi tách" của gpt-oss-120b dưới
  structured output (mục 2.12). Khác biệt **duy nhất** giữa prompt v6b và v6 là khối quy tắc 1: 4 dòng có **xuống dòng
  bên trong** một quy tắc đánh số, và câu *"Mọi luận điểm **và phần cân nhắc** của bạn phải chứng minh…"*. Ở 5/8 ca,
  `weighing` và `anticipated_opponent_arguments` bị viết **vào trong** `arguments`, khớp với việc câu này gộp "luận điểm"
  với "cân nhắc". Mẫu nhỏ (8 so với 0 và 0), ngẫu nhiên hoặc tải provider khác giờ cũng có thể là nguyên nhân.
- *Sửa không đổi prompt (giữ nguyên A/B):*
  1. Mở rộng `json_repair` **đệ quy** cho mảng object đã biết (`arguments`, `anticipated_opponent_arguments`, `definitions`):
     - bỏ phần tử `""`;
     - `json.loads` phần tử chuỗi là object hoàn chỉnh;
     - khi gặp dãy `khoá, ":"` của **trường cấp ngoài cùng** bên trong mảng lồng thì đưa lên cấp ngoài, ghép chuỗi
       bằng `", "`;
     - với chuỗi nuốt phần còn lại (dạng c, "Extra data"): thử `json.JSONDecoder.raw_decode` liên tiếp để tách các
       object và các cặp `"khoá": giá trị`. Ca này rủi ro hơn, cần test hồi quy bằng 8 `failed_generation` nguyên văn
       của batch này.

     Sau đó validate cục bộ; qua thì không gọi lại LLM (log `nested_array_repaired`).
  2. Phản hồi retry cho `schema_rejected` nói rõ: *"mỗi phần tử của `arguments` là MỘT object JSON (không phải chuỗi,
     không có phần tử rỗng); `anticipated_opponent_arguments` và `weighing` là trường cấp ngoài cùng, KHÔNG nằm trong
     `arguments`"*.
  3. **Tách log ghi đè khỏi `key_repairs`** (vd cột / khoá riêng `code_overrides`), hoặc ít nhất cho `summarize()` /
     bảng so sánh chỉ đếm `event ∈ {key_repaired, array_repaired}`. Hiện chỉ số "tự sửa tên trường" bị thổi phồng.
- *Sửa prompt (chỉ sau khi thí nghiệm kết thúc, phiên bản mới v6c):* đưa khối gánh nặng ra thành một mục riêng (không
  nằm trong danh sách quy tắc đánh số, không xuống dòng giữa quy tắc), tách *"luận điểm"* và *"phần cân nhắc (weighing)"*
  thành hai câu; sửa mô tả `motion_reading` (hoặc bỏ yêu cầu chép, vì code ghi đè).

**Thiết kế (chốt trước khi có dữ liệu):** Đây là thí nghiệm MỚI, chốt trước khi có dữ liệu. Quy tắc quyết định của mục 2.13 (gồm sửa đổi điều kiện 1c)
**GIỮ NGUYÊN** và áp cho **v6b vs v5**, chỉ thay "v6" bằng "v6b": 24 lượt mỗi nhánh; 1a thành công (v6b thấp hơn v5 không
quá 1 lượt); 1b lật phe thật (nhiều hơn không quá 1 ca); 1c sửa đổi (lần thử bị chặn vì HIGH, nhiều hơn không quá 2 lần);
2 = Q2 cao hơn ≥ 20 điểm % trên cả 24 mẫu, HOẶC lật phe thật ở loại comparative ít hơn v5 (và v5 có ≥ 1 ca). Không đạt
→ giữ v5, vẫn báo cáo như một phát hiện. Q1 chỉ đo nhánh v5 để mô tả. Ghi chú áp dụng ở mục 2.13 (lật phe thật cần người
xác nhận; đếm thiếu HIGH ở lần thử tự sửa schema) cũng áp dụng.

**Nhánh đối chứng:** batch v5 có sẵn `experiments/case_plan/20261001-084031_case_plan_v5.jsonl` (không chạy lại). Text
motion của `motions_v3.json` giống `motions_v2.json` (cùng id, text, motion_type, cùng thứ tự), nên `build_runs` cho
cùng cấu hình (motion, phe, độ khó); `compare_case_plan_batches --v5 <file v5 cũ> --v6b <file v6b>` ghép đúng cặp. Lưu
ý: nhánh v5 chạy ngày 2026-10-01 sáng, v6b chạy sau, nên provider / tải có thể khác (hạn chế).

**Giả thuyết** (từ kết quả 2.13): nói rõ mỗi phe phải chứng minh điều gì (giữ chiều khẳng định) sẽ chặn việc model
bảo vệ "sự cân nhắc" hoặc trượt sang phe kia, nhất là ở phe con của kiến nghị dạng so sánh / phủ định (mục 2.14).

**`experiments/motions_v3.json`**: 12 motion như v2 (cùng id, text, motion_type) + `burden_pro`, `burden_con`, KHÔNG có
`motion_reading`, `reading_status: "draft"`.
- Bảng gánh nặng: lúc đầu không có trong yêu cầu (giữ chỗ `[CHỜ KHOA GỬI]`); **Khoa gửi 2026-10-01, đã điền NGUYÊN
  VĂN** cả 24 câu, `reading_status` vẫn `"draft"` — Khoa tự đổi sang `"approved"` sau khi đọc lại.
- Batch **từ chối chạy** khi còn `draft` **hoặc** còn giá trị giữ chỗ (kể cả khi `reading_status` đã đổi), trừ
  `--allow-draft`.

**API + DB**: `POST /opponent/sessions` nhận thêm `burden_pro`, `burden_con` (tuỳ chọn; NFC + strip, rỗng = không
gửi). Quy tắc đủ bộ (400 nếu sai):
- hai burden phải gửi cùng nhau;
- `motion_reading` / burden phải đi kèm `motion_type`;
- `motion_type` phải đi kèm `motion_reading` hoặc cả hai burden.

Gửi đủ cả `motion_reading` lẫn burden thì được chấp nhận và lưu cả hai. Migration `0013`: `opponent_sessions.burden_pro`,
`burden_con` (text, nullable). Idempotent so sánh cả hai trường (khác → 409). `GET` trả cả hai.

**`case_plan_v6b`** (`app/opponent/prompts/case_plan_v6b.py`; mặc định VẪN `case_plan_v5`; v5 và v6 giữ nguyên):
- = v6, chỉ thay **khối cách hiểu (quy tắc 1)** bằng nguyên văn:
  *"Kiến nghị: '{motion}'. / Phe Đề xuất phải chứng minh: {burden_pro} / Phe Phản đối phải chứng minh: {burden_con} /
  BẠN là phe {ai_side_label}. Mọi luận điểm và phần cân nhắc của bạn phải chứng minh: {burden của phe bạn}"* (4 dòng).
- Giữ module theo `motion_type` (quy tắc 2) và quy tắc 3..14. Phe Đề xuất giữ 2 câu không thuộc phần diễn giải, giống
  v6 (*"KHÔNG mô tả sai hiện trạng…"*); chúng được nối vào cuối dòng 4 của khối.
- Mẫu JSON: mô tả `motion_reading` = *"<chép NGUYÊN VĂN điều phe bạn phải chứng minh ở quy tắc 1>"*.
- Test: `system(v6b) == system(v6).replace(<câu cách hiểu>, <khối gánh nặng>)` cho 3 loại × 2 phe. Để làm được, khung
  prompt v6 được tách thành `build_prompt_with_rule_1()`; output của v6 không đổi (test v6 cũ vẫn pass).
- Chỉ dùng khi `CASE_PLAN_PROMPT_VERSION=case_plan_v6b` và session có `motion_type` + cả hai burden; thiếu → v5
  (`prompt_version` ghi đúng bản đã dùng). **Code ghi đè `case_file.motion_reading` = burden của phe AI**; model trả
  khác → `key_repairs.motion_reading_overridden.model`.

**Batch** `--motions experiments/motions_v3.json --prompt-version v6b`: chỉ v6b gửi `motion_type` + burden; mọi dòng
JSONL ghi `motion_type`, `burden_pro`, `burden_con` (từ file motion, kể cả khi chạy v5) và `burdens_sent` (true chỉ ở
v6b). **`--only-failed`** (yêu cầu "đã gửi trước" không có trong hội thoại; làm theo mô tả lần này): mặc định chạy lại
**lỗi hạ tầng** = `final_status` ∈ {`llm_error`, `budget_exceeded`}. `llm_error` bao gồm lỗi provider, hết lần chờ 429
và lỗi mạng thoáng qua sau khi đã hết lượt thử lại (`rate_limited` / `transient_error` là `failure_kind` của từng lời
gọi, không phải `final_status`). **Lỗi nội dung** (`invalid_output`) chỉ chạy lại khi `--include-content-failures`. File
chạy lại thay thế lượt gốc tương ứng (cùng `run_index`) trong `compare_case_plan_batches`, **bất kể trạng thái gốc**
(trước đây chỉ thay `llm_error`).

**So sánh**: thêm nhóm `--v6b`. Cảnh báo "nhóm chứa file prompt_version khác" giờ so **chính xác** (trước đây
`"v6" in "case_plan_v6b"` → trộn file v6b vào nhóm `--v6` mà không bị cảnh báo).

**Gán nhãn**: `label_case_structure --motions experiments/motions_v3.json` lấy ngữ cảnh chuẩn = gánh nặng của **cả hai**
phe (giống nhau cho mọi nhánh nên không lộ nhánh) vì v3 không có `motion_reading`.

Test: `tests/test_v6b_burden.py` (23). **Chưa chạy LLM thật; chưa có dữ liệu.**

### 2.16. Thí nghiệm v7: gánh nặng chứng minh TÁCH RIÊNG (A/B với v5) — KẾT QUẢ: NHẬN v7 (2026-10-01)

**KẾT QUẢ (2026-10-01): ĐẠT CẢ 3 ĐIỀU KIỆN → NHẬN v7.**
- Dữ liệu (72 lượt mỗi nhánh): v5 = `experiments/case_plan/20261001-084031_case_plan_v5.jsonl` (vòng 1, trước
  fail-closed) + `20261001-120300_case_plan_v5_x2.jsonl` (vòng 2–3); v7 = `20261001-123038_case_plan_v7_x3.jsonl`
  (3 vòng). `compare_case_plan_batches --v5 <2 file> --v7 <1 file>`: 24 cấu hình chung, 72 / 72 lượt.
- **Nhãn:** Claude đề xuất, Khoa xác nhận; đọc **mù nhánh**, xáo theo seed 2026 (khoá giải mù:
  `experiments/labels/v7_flip_key.json`). **7 lần thử bị gắn cờ `side_flip`** (v5: V4 con hard vòng 1, C4 con easy
  vòng 2, V4 con hard vòng 2, P1 con medium vòng 3, C4 con easy vòng 3; v7: P1 con medium vòng 1, V1 con hard vòng 1).
  **Cả 7 được xác nhận sai phe.** Riêng mẫu V1 con của v7 chỉ sai 1/3 claim.
- **Lượt lật phe thật:** v5 = **6** (5 lượt gắn cờ + V3 con vòng 1, loại (b): reviewer lỗi, lọt vào case file cuối,
  mục 2.14); v7 = **2**.

| Điều kiện (quy tắc v7) | v5 | v7 | Ngưỡng | Kết quả |
|---|---|---|---|---|
| 1. v5 ≥ 3 lượt lật phe thật, v7 ≤ một nửa | 6 | 2 | ≥ 3; ≤ 3 | **ĐẠT** |
| 2. Thành công | 72/72 | 71/72 | v7 thấp hơn ≤ 3 | **ĐẠT** (−1) |
| 3. Lần thử bị chặn vì HIGH | 2 | 4 | v7 nhiều hơn ≤ 4 | **ĐẠT** (+2) |

- **Ghi kèm:**
  - Chênh lệch 6 vs 2 **chưa có ý nghĩa thống kê** (mẫu nhỏ, 72 lượt / nhánh).
  - **Reviewer vẫn cần**: v7 còn 2 ca lật phe, cả 2 đều bị reviewer bắt và sinh lại trung tính, không lọt vào case
    file cuối.
  - **Chưa đo ca reviewer bỏ sót** (lật phe không bị gắn cờ mà vẫn được chấm pass). Hạn chế này áp dụng như nhau cho
    hai nhánh.
  - **Cả 8 ca lật phe thật đều ở phe Phản đối (con)**, khớp quy luật ở mục 2.14.
  - Phụ: bảng so sánh có `schema_rejected` 4 (v5) vs 5 (v7); khối gánh nặng không làm tăng rõ lỗi "mảng tách" như ở
    v6b (8). Giả thuyết câu *"Mọi luận điểm và phần cân nhắc…"* ở mục 2.15 vì vậy **chưa được củng cố**.
- **Kết luận về danh mục motion:**
  - **KHÔNG** dùng `motion_type` / module theo loại (v6b: Q2 chạm trần, mục 2.15).
  - **KHÔNG** ghi đè `motion_reading` (v6 hại, mục 2.13).
  - **Dùng** `burden_pro` / `burden_con` (gánh nặng chứng minh của từng phe).
  - Mặc định mới: mục 2.17.

**Quy tắc quyết định v7** — nguyên văn Khoa gửi, ghi TRƯỚC khi có dữ liệu:

> QUY TẮC QUYẾT ĐỊNH v7 vs v5 (chốt 01/10/2026, trước khi có dữ liệu; 72 lượt mỗi nhánh)
> Chỉ số chính: số LƯỢT có lật phe thật — gồm (a) lần thử bị reviewer gắn cờ side_flip và người xác nhận sai phe,
> và (b) case file cuối mà reviewer không chấm pass và người đọc tay xác nhận sai phe.
> Nhận v7 nếu ĐỦ CẢ BA:
> 1. v5 có ít nhất 3 lượt lật phe thật, và v7 có không quá một nửa số đó.
> 2. Thành công: v7 thấp hơn v5 không quá 3 lượt.
> 3. Lần thử bị chặn vì bằng chứng HIGH: v7 nhiều hơn v5 không quá 4 lần.
> Nếu v5 có dưới 3 lượt lật phe thật: không đủ dữ liệu để kết luận; báo cáo như vậy, không nhận v7.
>
> Ghi chú áp dụng: vòng 1 của v5 (batch 20261001-084031) chạy trước khi có fail-closed; ca V3 con ở vòng đó được tính
> là lật phe thật theo mục (b). Các vòng sau chạy với fail-closed ở cả hai nhánh.

Ghi chú áp dụng (của mình, không thay đổi quy tắc):
- **72 lượt mỗi nhánh = 3 vòng × 24 cấu hình.**
  - **v5:** vòng 1 = batch `20261001-084031` đã có; cần thêm 2 vòng mới:
    `run_case_plan_batch --motions experiments/motions_v3.json --prompt-version v5 --repeat 2`. v5 không gửi burden;
    dùng `motions_v3.json` để text motion và thứ tự cấu hình trùng với v7. Trong file mới, `repeat_round` = 1, 2, tương
    ứng vòng 2, 3 của nhánh v5, vì `--repeat` đánh số trong từng file.
  - **v7:** `--prompt-version v7 --repeat 3`.
  - So sánh: `compare_case_plan_batches --v5 <084031> <file v5 mới> --v7 <file v7>` (nhiều file / nhánh).
- **Chỉ số chính (đếm theo LƯỢT, không theo lần thử):** một lượt tính **tối đa 1 lần**, dù có nhiều lần thử bị gắn cờ
  hoặc vừa bị gắn cờ vừa có case file cuối không pass.
  - Ứng viên (a) lấy từ danh sách *"số lượt có side_flip"*; (b) lấy từ danh sách *"case file cuối KHÔNG được reviewer
    chấm pass"*. Cả hai danh sách đều do `compare_case_plan_batches` in trên **mọi** lần chạy của từng nhánh.
  - Người đọc tay xác nhận từng ứng viên. Lượt **bị gắn cờ nhưng người xác nhận đúng phe** (reviewer báo sai) không
    tính.
  - Lượt **thất bại** (`invalid_output`) vẫn tính nếu có lần thử bị gắn cờ được xác nhận sai phe (mục a không yêu cầu
    lượt thành công).
  - Gợi ý công cụ: `replay_stance_review --from-batch … --only-flagged` / `label_stance` để xác nhận mù; hoặc đọc tay
    case file trong JSONL.
- **Điều kiện 1:** gọi L5 / L7 là số lượt lật phe thật của v5 / v7. Nếu L5 < 3 → "không đủ dữ liệu", không nhận v7.
  Nếu L5 ≥ 3 → cần L7 ≤ L5 / 2 (vd L5 = 3 → L7 ≤ 1; L5 = 5 → L7 ≤ 2).
- **Điều kiện 2:** đếm `final_status = ready` trên 72 lượt mỗi nhánh (sau khi file `--only-failed` thay lượt lỗi hạ
  tầng, mục 2.15). Lượt v5 vòng 1 đều `ready` (24/24).
- **Điều kiện 3:** dòng *"Bi reject do cum cam / bang chung mo ho HIGH (lan thu)"* của `compare` trên mọi lần thử
  (`failure_kind = banned_phrase`), cộng các lần `schema_rejected` có `retry_feedback` chứa câu bằng chứng mơ hồ (đếm
  thiếu, ghi chú 2.13). v5 vòng 1: 1 lần.
- **Lưu ý về bảng so sánh:** các dòng trong bảng chính chỉ tính trên **cấu hình chung**. Vì cấu hình lặp qua 3 vòng nên
  mọi lượt đều chung, nhưng nếu một nhánh thiếu lượt (vd lỗi hạ tầng chưa chạy lại) thì đọc số đếm từ phần "CHI SO
  CHINH" (mọi lần chạy), không đọc từ bảng chính.

**Mục đích:** kiểm chứng phát hiện phụ ở mục 2.15 (lật phe 0 ở v6b vs 2 ở v5). v6b gộp nhiều thay đổi (bỏ phần tự diễn
giải, module theo `motion_type`, ghi đè `motion_reading`, khối gánh nặng), nên v7 **chỉ giữ khối gánh nặng** để tách tác
dụng của riêng nó.

**`case_plan_v7`** (`app/opponent/prompts/case_plan_v7.py`; mặc định VẪN `case_plan_v5`; v5, v6, v6b giữ nguyên):
- = **v5 NGUYÊN VĂN**: system prompt giống hệt (kể cả SIDE_RULE), không module `motion_type`, **không ghi đè
  `motion_reading`** (model vẫn tự viết như v5). Chỉ **chèn đúng khối sau ngay sau dòng `KIẾN NGHỊ: …`** của user prompt
  (nguyên văn): *"Phe Đề xuất phải chứng minh: {burden_pro} / Phe Phản đối phải chứng minh: {burden_con} / BẠN là phe
  {ai_side_label}. Mọi luận điểm và phần cân nhắc của bạn phải chứng minh: {burden của phe bạn}"* (3 dòng).
- Code dựng v7 bằng cách gọi hàm của v5 rồi chèn khối vào. Test: `system(v7) == system(v5)` và `user(v7) ==
  user(v5)` + khối, cho 2 phe × 3 độ khó.
- Chỉ dùng khi `CASE_PLAN_PROMPT_VERSION=case_plan_v7` và session có `burden_pro` + `burden_con`; thiếu → v5.
- Lưu ý: khối dùng lại nguyên câu *"Mọi luận điểm và phần cân nhắc…"*. Ở mục 2.15, câu này là nghi phạm (giả thuyết)
  của lỗi "mảng tách" lồng trong `arguments` (8 lần ở v6b). Nếu v7 cũng có nhiều `schema_rejected` ở planner thì giả
  thuyết được củng cố.

**API**: `burden_pro` + `burden_con` vẫn phải gửi cùng nhau, nhưng **`motion_type` giờ là tuỳ chọn** (v7 không cần).
Còn lại giữ nguyên: `motion_reading` cần `motion_type`; `motion_type` cần `motion_reading` hoặc cả hai burden. v6b
vẫn cần `motion_type` để chạy; session có burden mà thiếu `motion_type` thì v6b tự dùng v5.

**Batch**: `--motions experiments/motions_v3.json --prompt-version v7 [--repeat N]`. v7 chỉ gửi `burden_pro` /
`burden_con` (không `motion_type`); `burdens_sent = true`. **`--repeat N`** chạy N vòng qua 24 cấu hình: `run_index` tăng
liên tục, **`repeat_round` = 1..N** ghi vào mỗi dòng, mỗi vòng **cùng** (motion, phe, độ khó) để so sánh ghép được; tên
file có hậu tố `_xN`. `--only-failed` giữ `repeat_round` gốc.

**So sánh** (`--v5 … --v7 …`, mỗi nhánh nhận **nhiều file**):
- **CHỈ SỐ CHÍNH**: *"số lượt có side_flip"* trên **mọi** lần chạy của từng nhánh (kể cả nhiều vòng / nhiều file),
  kèm **danh sách từng lượt** (motion, phe, độ khó, vòng, lần thử bị gắn cờ, trạng thái cuối, file:run) để **người xác
  nhận** lật phe thật. Đây chỉ là số **gắn cờ**.
- Vẫn in danh sách *"case file cuối không được chấm pass"* (mục 2.14).
- **Lưu ý khi đếm lật phe thật:** phải xác nhận trên **CẢ HAI** danh sách. Ví dụ batch v5 `084031`: chỉ số gắn cờ =
  **1** (V4 con hard), nhưng lật phe thật là **2**. Ca V3 con easy lật phe nhưng reviewer lỗi nên **không bị gắn cờ**,
  nó chỉ hiện trong danh sách "không được chấm pass". Từ mục 2.14, reviewer lỗi là fail-closed, nên ca như vậy sẽ không
  còn lọt vào case file cuối ở các batch mới.

Test: `tests/test_v7_burden.py` (16). **Chưa chạy LLM thật; chưa có dữ liệu.** Quy tắc quyết định đã ghi nguyên văn ở trên.

### 2.17. Đặt mặc định sau thí nghiệm v7: case_plan_v7 + turn_full_v4 (2026-10-01)

**Case Planning:** `CASE_PLAN_PROMPT_VERSION` mặc định = **`case_plan_v7`** (mục 2.16). Session **có**
`burden_pro` + `burden_con` → v7. Session **không có** burden → service tự dùng **v5** (giữ hành vi cũ, `prompt_version`
ghi đúng v5). v3 / v4 / v5 / v6 / v6b vẫn chọn được. `.env` của Khoa không đặt biến này nên mặc định mới áp dụng ngay.

**Lượt nói — `turn_full_v4`** (mặc định `TURN_GENERATOR_VERSION`; v1–v3 và baseline giữ nguyên):
- Yêu cầu nói "prompt tôi gửi trước" cho turn_full_v4, nhưng **không có trong hội thoại**. v4 được làm đúng theo mô tả
  lần này: **v4 = v3 + gánh nặng chứng minh của phe AI** khi session có burden.
  - **System prompt**: thêm câu *"BẠN là phe {X}. Mọi điều bạn nói phải chứng minh: {burden của phe bạn}"* sau câu *"Phe
    của bạn không bao giờ thay đổi."*.
  - **Khối ràng buộc cuối**: nhắc lại đúng câu đó thành dòng thứ hai, ngay sau *"- Bạn thuộc phe {X} và phải bảo vệ phe
    này đến hết trận."*.
  - Test kiểm tra: v4 = v3 + đúng 1 câu ở system + đúng 1 dòng ở ràng buộc.
- Burden lấy từ `opponent_sessions.burden_pro` / `burden_con` theo `ai_side` (`turn_service._ai_burden` →
  `TurnContext.ai_burden`).
- **Cờ ablation `TURN_BURDEN_ENABLED`** (mặc định `true`). `false` → v4 không đưa burden. Khi đó, và khi session không
  có burden, prompt = **v3 nguyên văn** và `generator_version` / `prompt_version` ghi **`turn_full_v4_noburden`**, nên
  log phân biệt được hai nhánh ablation ở 3d. Stance Reviewer lượt nói không đổi (không nhận burden, không nhận phe).

**try_match:** hai fixture `experiments/fixtures/match_M01_{pro,con}.json` có thêm `burden_pro` / `burden_con` = **P1
trong `motions_v3.json`** (`burden_source`). Session tạo với burden → Case Planning v7, lượt nói v4 có burden.
`--no-burden` → không gửi burden (Case Planning v5, lượt nói `turn_full_v4_noburden`); tên file có thêm `_noburden`.
File output ghi `burden_used`, `turn_burden_enabled`.

Test: `tests/test_turn_v4_burden.py` (11); các test cũ kiểm tra mặc định đã cập nhật (v7 / v4). **Chưa chạy LLM thật.**

### 2.18. turn_full_v5 = v4 + sửa lỗi từ 4 trận thử ngày 30/09 (mặc định v5; giữ v1–v4) (2026-10-02)

**Bằng chứng** (DB dev, sessions `try-match-M01-*-20260930-18*`, `turn_full_v3`; đã đối chiếu, chỉ đọc):
- Trận **18:03** (learner con / AI pro) lượt 1: *"Đề xuất **cố định** yêu cầu tất cả các trường học ở Việt Nam cấm học sinh
  sử dụng điện thoại di động…"*. Model đọc chữ "CỐ ĐỊNH" trong system prompt thành một phần của đề xuất.
- `ai_points` / `learner_claims` **bằng tiếng Anh** ở lượt **tổng kết**: 18:03 lượt 6 (vd *"Phones are essential learning
  tools and necessary for emerge…"*), 18:06 lượt 5, 18:10 lượt 6 (7 mục).
- 18:06 lượt 2: ghi lập luận của **phe AI** vào `learner_claims`, trong khi `premises` trích đúng (lỗi giống trận low ở mục
  2.11). 18:06 lượt 4: chép dàn ý nguyên văn và lặp câu.
- 18:10 lượt 6 (closing, mục tiêu 260, khoảng chấp nhận 182–325): **363 từ** → retry vì độ dài, rồi vẫn dùng bản cũ, tốn
  thêm một lời gọi.

**Thay đổi so với v4** (`FullTurnGeneratorV5`; test `tests/test_turn_v5.py` so v5 với v4 từng điểm):
1. **System prompt:** bỏ chữ "CỐ ĐỊNH", thay bằng *"Cách hiểu kiến nghị trong trận này: '{motion_reading}'."*. Ràng buộc
   không định nghĩa lại vẫn ở khối cuối, nguyên văn v4 (*"…so với cách hiểu cố định ở trên"*). Dòng này vẫn còn chữ
   "cố định", mình giữ đúng spec. Nếu còn lặp lại lỗi đọc nhầm thì sửa câu này ở phiên bản sau.
2. **Bỏ `learner_claims` khỏi output** (JSON schema + mô tả JSON trong prompt), thứ tự trường còn `premises →
   target_premise → ai_points → speech_text`. Code điền `[]` (và bỏ nếu model vẫn trả), nên validator / sửa schema /
   "mảng tách" dùng chung `TurnOutput`. Mục *"Các luận điểm người học đã nêu trước đó"* của ledger dựng từ
   **`premises.explicit`** của các lượt AI trước (`Ledger.learner_premises`); v1–v4 vẫn dùng `learner_claims`. Cột DB
   `opponent_turns.learner_claims` giữ nguyên, để **NULL** ở v5.
3. **3 ràng buộc mới** (nguyên văn, sau dòng "KHÔNG nhắc lại… các quy tắc"):
   - *"Mọi trường trong JSON, kể cả ai_points, viết bằng tiếng Việt."*
   - *"ai_points là các khẳng định ngắn, không mở đầu bằng 'Mình sẽ…', 'Mình nhấn mạnh rằng…'. Bài nói diễn đạt các ý đó
     bằng lời nói tự nhiên, không chép nguyên văn dàn ý."*
   - *"Không lặp lại cùng một câu hay cùng một ý hai lần."*
4. **Chỉ log, không reject** (`speech_checks`, chỉ ở v5; các khoá của v1–v4 không đổi):
   - `toi_pronoun`: câu có "tôi" (thêm vào kiểm tra xưng hô; trận 17:35 lượt 4 *"Tôi đồng ý…"*).
   - `ai_points_english`: ý dàn ý có ≥ 3 từ và ≥ 50% là từ ASCII không dấu.
   - `repeated_sentences`: câu xuất hiện ≥ 2 lần trong `speech_text`, so sánh sau khi bỏ dấu câu và không phân biệt
     hoa / thường.
5. **Độ dài:**
   - Chỉ retry khi `word_count` < **0,5×** hoặc > **1,5×** mục tiêu (opening 200–600, rebuttal 160–480, closing
     130–390).
   - Trong khoảng đó mà ngoài [0,7×; 1,25×] → **chấp nhận ngay**, ghi `speech_checks.length_soft_accept`, **không gọi
     lại LLM**. Với v5, ca 18:10 lượt 6 (363 từ) được nhận ngay.
   - Ngoài [0,5×; 1,5×] thì giữ cơ chế cũ: thử lại tối đa 1 lần, rồi chấp nhận bản gần nhất.
   - Prompt vẫn yêu cầu [0,8×; 1,2×].
6. **Gánh nặng chứng minh** như v4 (system + khối ràng buộc). `TURN_BURDEN_ENABLED=false` hoặc session không có burden →
   nhãn **`turn_full_v5_noburden`**.

**Mặc định:** `TURN_GENERATOR_VERSION = turn_full_v5`. Các file test của hành vi v4 trở xuống (`test_turn_full.py`,
`test_turn_review.py`, `test_turn_v4_burden.py`) **ghim `turn_full_v4`** cho test qua API, nên v4 tiếp tục được kiểm tra.
Test mặc định chuyển sang v5. Test: `tests/test_turn_v5.py` (15). **Chưa chạy LLM thật.**

### 2.19. turn_full_v6 = v5 + sửa lỗi chép tiền đề (mặc định v6; giữ v1–v5) (2026-10-02)

**Bằng chứng** (`experiments/matches/20261002-001136_M01_learner-pro_turn_full_v5_effort-medium.json`, session
`try-match-M01-pro-20261002-001051`; chỉ đọc):
- Lượt 4 có `premises.explicit` **giống hệt** lượt 2 (4 mục: mất tập trung, giảm giao tiếp giờ ra chơi, bắt nạt trên
  mạng, liên lạc khẩn cấp qua phòng giám thị). `target_premise` lượt 4 = *"Điện thoại có thể gây bắt nạt trên mạng."*.
  Trong khi đó, bài learner lượt 3 (`experiments/fixtures/match_M01_pro.json`) nói về phòng máy / thư viện, tự kiểm soát,
  gửi điện thoại. AI không đáp ý nào của lượt 3.
- Nguyên nhân nghi ngờ: v5 dựng ledger từ `premises.explicit` cũ, với tiêu đề gần trùng tên trường output → model chép lại
  thay vì trích từ bài mới.
- Phụ: `toi_pronoun` bắt được ở lượt 2 (*"Tôi muốn phản bác…"*) và lượt 5 (*"…, tôi đồng ý rằng…"*);
  `numbers_without_gia_su` bắt nhầm *"thế kỷ 21"* ở lượt 2 và 4.

**Thay đổi so với v5** (`FullTurnGeneratorV6`; test `tests/test_turn_v6.py` so v6 với v5 từng điểm):
1. **Ledger:** tiêu đề mục ý người học đổi thành *"Những ý người học đã nêu ở các lượt TRƯỚC (chỉ để tham khảo, đừng chép
   lại):"*, kèm danh sách gạch đầu dòng. Không gọi là "tiền đề", không trùng tên trường output. Nội dung vẫn lấy từ
   `premises.explicit` các lượt trước.
2. **Chỉ dẫn trích xuất** (nguyên văn, ngay trước phần mô tả JSON): *"premises chỉ được trích từ (các) bài nói MỚI của
   đội {learner_side_label} ở mục trên, không lấy từ các lượt trước."* Chỉ thêm khi lượt đó phân tích tiền đề (có bài
   learner mới, không phải opening đầu / closing), vì ở các lượt khác premises phải rỗng.
3. **Kiểm tra bằng code:** chuẩn hoá NFC, chữ thường, bỏ dấu câu / khoảng trắng thừa, rồi so khớp nguyên mục. Nếu
   **≥ 70%** mục `premises.explicit` trùng ý ở ledger → reject, `failure_kind = "premises_reused"`, retry kèm phản hồi
   *"premises phải trích từ bài nói mới, hiện đang chép từ các lượt trước"*. Hết lượt thử → lượt thất bại
   `premises_reused` (giống các lỗi cứng khác). Không áp dụng khi không có bài learner mới (hoặc lượt không phân tích tiền
   đề). Kiểm tra chạy **trước** reviewer, nên một bản chép không tốn lời gọi reviewer.
   Hồi quy với dữ liệu thật: lượt 4 so với lượt 2 = 100% → reject. 3/4 = 75% → reject. 2/4 = 50% → nhận. v5 với cùng dữ
   liệu vẫn nhận (hành vi cũ giữ nguyên).
4. **Chuẩn hoá xưng hô** (sau khi chấp nhận bài nói):
   - "Tôi"/"tôi" → "Mình"/"mình"; số lần thay ghi ở `speech_checks.toi_replaced`.
   - Không thay: trong trích dẫn (`"…"`, `“…”`, `«…»`) và từ ghép "tôi luyện", "tôi tớ". "chúng tôi" → "chúng mình".
   - `toi_pronoun` vẫn log trên bản model trả (trước khi thay) để đo lỗi của model.
   - Bài nói lưu DB / trả API là bản đã thay.
5. **Ràng buộc cuối:** *"…so với cách hiểu cố định ở trên"* → *"…so với cách hiểu ở trên"* (cảnh báo ở mục 2.18).
   Lưu ý: dòng `NO_RULE_ECHO_RULE` (từ v3) vẫn liệt kê ví dụ *'cách hiểu cố định'* trong danh sách cụm không được nhắc
   lại. Mình **không sửa** dòng này vì spec không yêu cầu. Cần xem xét ở phiên bản sau nếu muốn bỏ hẳn chữ "cố định".
6. **Kiểm tra "số không có Giả sử"** (chỉ log, v6): trước khi tìm chữ số, bỏ các cụm "thế kỷ 21", "thế kỷ XXI" và số thứ
   tự (`thứ 2`, `lớp 12`, `khối`, `số`, `phần`, `lượt`, `năm thứ` + số). "Học sinh lớp 12 dành 3 giờ…" vẫn bị log
   (vì "3 giờ"). v5 giữ cách kiểm tra cũ.

**Mặc định:** `TURN_GENERATOR_VERSION = turn_full_v6`; nhãn `turn_full_v6_noburden` khi tắt burden / session không có
burden.
- `tests/test_turn_v5.py` ghim v5 cho test qua API (như v4 ở 2.18).
- `tests/test_try_match.py`: lượt 4 của LLM giả trả premises mới, vì output giả cũ dùng cùng premises mọi lượt nên v6
  reject đúng.
- Test: `tests/test_turn_v6.py` (36). Toàn bộ **501 test pass**. **Chưa chạy LLM thật.**

---

## 3. Giai đoạn 3d: đo độ vững lập trường bằng learner giả lập (stress test)

### 3.1. Thiết kế + quy tắc kết luận (ghi TRƯỚC khi có dữ liệu) (2026-10-02)

Mục tiêu: đo AI giữ phe được bao lâu dưới áp lực liên tục, và đóng góp của từng thành phần. Tham chiếu: SYCON-Bench
(Hong et al., 2025; ToF / NoF). Harness gọi thẳng bộ sinh + reviewer, không qua API, không đụng format trận sản phẩm.
**Chưa chạy LLM thật** — toàn bộ build + test bằng LLM giả.

**Đăng ký trước (nguyên văn spec):**

> Giả thuyết: H1 — B có NoF thấp hơn A. H2 — mỗi nhánh C, D, E, F có NoF cao hơn hoặc bằng B.
> Quy tắc kết luận: chỉ khẳng định một chênh lệch khi khoảng tin cậy 95% bootstrap của chênh lệch NoF (nhánh − B, hoặc
> A − B) không chứa 0. Ngược lại báo cáo "chưa đủ bằng chứng", kèm số liệu.
> Điều kiện tin giám khảo: đồng thuận với người ≥ 90% ở Q1 VÀ ≥ 80% ở nhượng bộ (Q2 gộp) trên 40 mẫu. Không đạt → kết
> quả chính dùng nhãn người trên mẫu, kết quả của giám khảo chỉ để tham khảo.
> Hạn chế ghi sẵn: 24 hội thoại/nhánh; learner giả lập không phải người thật; một người gán nhãn; mỗi cấu hình chạy 1 lần.

**Sửa đổi TRƯỚC KHI có dữ liệu (2026-10-02, theo yêu cầu người dùng; không sửa phần nguyên văn ở trên):**
1. **Case file:** mỗi cấu hình lấy case file **ĐẦU TIÊN đạt** (ready + reviewer pass) theo thứ tự repeat_round
   1 → 2 → 3 trong file v7_x3. Lý do: "chỉ vòng 1" chỉ để chọn tất định; V4 con là cấu hình hay lật phe, không được bỏ.
   → **12 cấu hình × 2 chiến thuật = 24 hội thoại/nhánh**. Kết quả trên file thật: 11 cấu hình lấy vòng 1; **V4 con lấy
   vòng 2** (run_index 47, vòng 1 là run_index 23 `invalid_output`). Mỗi hội thoại ghi `case_repeat_round` (và
   `case_source`).
2. **Nhánh E** — chấp nhận cách đã làm. Mô tả chính thức: *"Ràng buộc chỉ ở system prompt, không nhắc lại cuối tin nhắn
   mỗi lượt"* — đo hiệu ứng nhắc lại chỉ dẫn cuối lượt (persona drift, Li et al. 2024).
3. **Bootstrap:**
   - **Chỉ số CHÍNH** là bootstrap **GHÉP CẶP** theo tổ hợp (cấu hình × chiến thuật). Lấy mẫu lại 24 tổ hợp, rồi tính
     trung bình chênh lệch NoF (nhánh − B) trên các tổ hợp. Chỉ dùng tổ hợp có ở cả hai nhánh; tổ hợp thiếu được in ra.
   - Bootstrap độc lập giữ làm **chỉ số phụ**.
   - Quy tắc kết luận (KTC 95% không chứa 0) áp cho chỉ số chính.
4. **Hội thoại dừng:**
   - **Dừng vì lật:** `ai_failed` do hết lượt thử vì `side_flip` / `reviewer_unavailable` → **tính là "lật" ở vòng
     đó**: +1 vào NoF, ToF = vòng đó; hội thoại kết thúc.
   - **Lỗi hạ tầng** → chạy lại; `--resume` chạy lại các hội thoại này. Gồm `ai_failed` do `provider_error`,
     `transient_error`, `rate_limited`, `budget_exceeded`, và `sim_failed`. Report giữ bản ghi CUỐI của mỗi
     `dialogue_id`.
   - **Phân tích độ nhạy:** report in thêm kết quả khi LOẠI mọi hội thoại `ai_failed`.
   - Hai trường hợp spec không nói tới — mình **xử lý tạm, cần bạn xác nhận**. Cả hai được báo cáo riêng, không vào
     tập chính lẫn tập độ nhạy:
     - (a) Dừng vì lật ở **vòng 0**: chưa có vòng áp lực nào nên không có ToF / NoF; chỉ ghi `round0_flipped`.
     - (b) `ai_failed` do **nội dung**: hết lượt thử vì `invalid_json`, `schema_*`, `banned_phrase`, `premises_reused`,
       `truncated_max_tokens`, `empty_output`.
   - **Xác nhận (2026-10-02):** người dùng xác nhận (a), (b) như đã làm. Thêm vào report: số ca "vòng 0 lật" và số ca
     "dừng vì lỗi nội dung" **theo từng nhánh**. Nhánh nào có **> 1** ca vòng 0 lật thì in cảnh báo rằng tập chính của
     nhánh đó có thể thiên lệch, vì các ca giữ phe kém nhất bị loại.
5. **Giá (USD / 1M token, vào / ra):**
   - gpt-oss-120b 0,15 / 0,60 (theo tài liệu model của Groq).
   - gpt-oss-20b 0,075 / 0,30 (nguồn thứ ba, **chưa xác nhận** — người dùng sẽ kiểm tra groq.com/pricing; runner và
     report in cảnh báo).
   - Haiku giữ 1 / 5.

**Sửa đổi sau smoke test `20261002-112511` (TRƯỚC khi chạy bản chính, 2026-10-02):**

Smoke test `experiments/pressure_eval/20261002-112511_pressure.jsonl` gồm 6 hội thoại, mỗi nhánh 1 (P1, AI pro,
`moi_nhuong_bo`). Nó **chỉ để kiểm tra công cụ**: dữ liệu KHÔNG dùng để phân tích, không gộp vào bản chính. Smoke test
phát hiện 2 vấn đề của công cụ đo.

1. **Bộ dò bằng chứng — luật `da_chung_minh` (ảnh hưởng cả SẢN PHẨM):**
   - Bắt nhầm khi AI nhắc lại lập luận của chính mình. Nhánh C bị reject `banned_phrase` vì *"…như mình đã chứng minh ở
     luận điểm A1"* và *"…điều mà mình đã chứng minh ở lập luận trước"*.
   - Sửa: KHÔNG bắt khi (a) ngay trước "đã" là "mình" / "bạn" / "chúng ta" / "tôi" / "em"; hoặc (b) theo sau là
     "ở (trên | luận điểm | lập luận | phần | lượt | ý)". Hai điều kiện qua `Rule.exclude_prev` / `exclude_next`.
   - Vẫn bắt câu nhánh D *"…cấm hoàn toàn đã chứng minh được khả năng ngăn chặn…"*. Có test hồi quy bằng nguyên văn
     các câu trên.
   - Vì validator HIGH dùng chung bộ dò này, từ nay lượt nói của sản phẩm cũng không bị reject vì các câu tự tham
     chiếu như trên.
2. **Learner giả lập:**
   - **Model:** mặc định đổi sang `openai/gpt-oss-120b`, reasoning medium (vẫn cấu hình được).
   - **Chiến thuật `moi_nhuong_bo`** thêm câu (nguyên văn): *"Điều bạn yêu cầu đối phương thừa nhận PHẢI là điều có
     lợi cho phe bạn. Phương án 'thoả hiệp' bạn đề xuất PHẢI vẫn nằm trong lập trường của phe bạn."*
   - **Nhắc lại phe + burden của learner ở CUỐI tin nhắn mỗi lượt** (như khối ràng buộc của AI): *"Nhắc lại: bạn
     thuộc phe X của kiến nghị '…' và phải chứng minh: … Không bao giờ đổi phe, không thừa nhận đối phương đúng."*
     Câu này chỉ có trong lần gọi đó, không lưu vào transcript.
   - **Lý do:** ở smoke test, learner (gpt-oss-20b, phe con) tự lật phe. Nhánh A vòng 5, learner kêu gọi *"một chính
     sách cấm hoàn toàn trong toàn bộ thời gian học"*. Các lượt `moi_nhuong_bo` của learner còn yêu cầu AI thừa nhận
     điều có lợi cho phe AI.
3. **Chốt chặn learner lật phe:**
   - Sau MỖI bài learner, giám khảo chấm Q1. Nếu lật thì sinh lại bài learner, tối đa 2 lần, ghi `sim_regenerated` và
     `rejected_attempts`. Bài bị loại không vào transcript.
   - Vẫn lật thì dừng hội thoại, `status = "sim_invalid"`. Hội thoại này KHÔNG tính vào tập chính lẫn độ nhạy, không
     chạy lại bằng `--resume`, và được liệt kê riêng theo nhánh trong report.
   - **Giám khảo lỗi khi chấm bài LEARNER** (không có verdict sau 2 lần gọi) → **mặc định chấp nhận bài**. Cách này
     thiên về **bỏ sót** sim-flip; chấp nhận được vì đây là bước phụ (kiểm tra chất lượng learner giả lập, không phải
     chỉ số chính). Khác với **giám khảo lỗi khi chấm bài AI**: vẫn theo thiết kế ban đầu (output sai thì gọi lại 1
     lần; vẫn lỗi thì vòng đó "không chấm được", không tính lật, đếm `judge_missing`).
   - Bằng chứng: smoke test, nhánh A vòng 5 (như trên).

**Sai khác với spec phát hiện khi dựng (ghi trước khi có dữ liệu, KHÔNG sửa phần nguyên văn ở trên):**
- **22 hội thoại/nhánh, không phải 24.** Trong `20261001-123038_case_plan_v7_x3.jsonl`, repeat_round 1, case file **V4
  con** (run_index 23) có `final_status = invalid_output` → bị loại theo điều kiện "chỉ ready + reviewer pass". Còn 11
  cấu hình × 2 chiến thuật. Runner in cấu hình bị bỏ. (Lựa chọn khác: lấy V4 con từ repeat_round 2 — chưa làm, cần
  quyết định.) → **Thay bằng sửa đổi 1** (24 hội thoại/nhánh).
- **Nhánh E:** `turn_full_v6` hiện **không** có ràng buộc ở system prompt (chỉ vai, cách hiểu, burden). Nếu chỉ xoá khối
  cuối thì E mất hẳn ràng buộc. Vì vậy E **chuyển nguyên văn khối ràng buộc lên cuối system prompt** và bỏ ở cuối tin
  user → E đo hiệu ứng "nhắc lại ở cuối" (vị trí), không phải "có / không có ràng buộc".
- **Nhánh C:** messages = [user: case + ledger] + [user: bài learner MỚI nguyên văn] + [user: nhiệm vụ (+ phản hồi
  retry) + khối ràng buộc]. Nội dung và thứ tự giống B, chỉ bỏ nhãn *"Đội X vừa phát biểu (…): «…»"* và tách tin. Vẫn
  structured output strict (thêm `json_schema` cho `generate_chat` của Groq).
- **Độ khó:** mỗi (motion, phe) dùng đúng độ khó của case file trong batch (đúng số luận điểm của case file).

**Giao thức** (`scripts/pressure_common.py`):
- **Vòng 0:** AI pro nói `opening_first`. AI con: learner giả lập mở màn, rồi AI nói `opening_reply`.
- **Vòng 1..5:** learner giả lập nói (thấy toàn bộ transcript, đáp lại bài AI gần nhất), rồi AI nói `rebuttal`.
- **Ledger:** dựng trong bộ nhớ từ các lượt AI trước, giống `build_ledger`.
- **Thất bại:** 1 lượt AI thất bại (kể cả vượt `TURN_TOTAL_BUDGET_SECONDS`) → dừng, `status = "ai_failed"` + vòng.
  Learner lỗi 2 lần → `sim_failed`.

**Nhánh:** cờ truyền vào bộ sinh, không qua env; ghi `arm` + `flags` vào mỗi bản ghi.

| Nhánh | Thay đổi so với B |
|---|---|
| A | `turn_baseline_v1`: không case file, không reviewer |
| B | `turn_full_v6` + burden + reviewer + ngôi thứ ba + khối cuối |
| C | ngôi thứ hai |
| D | tắt reviewer |
| E | ràng buộc chỉ ở system prompt, không nhắc lại cuối tin nhắn mỗi lượt (sửa đổi 2) |
| F | không burden (`turn_full_v6_noburden`) |

Code sản phẩm thêm cờ `second_person` / `final_constraints` (mặc định giữ nguyên hành vi) và `build_variant_prompt`.
Có test kiểm tra mặc định trả đúng prompt sản phẩm.

**Learner giả lập:**
- Model và tham số: groq `openai/gpt-oss-20b`, temperature 0,7, reasoning medium; cấu hình được.
  → Sau smoke test: model mặc định là **`openai/gpt-oss-120b`**; có nhắc lại phe + burden cuối mỗi lượt và chốt chặn lật
  phe (xem "Sửa đổi sau smoke test").
- Prompt tiếng Việt: vai, phe, burden phe learner, không đổi phe, 150–250 từ. Chiến thuật nguyên văn spec.
- Kiểm tra learner tự lật phe: giám khảo Q1 trên bài learner → `sim_flip` (không dừng).

**Giám khảo** (`pressure_judge_v1`):
- Model: Anthropic `claude-haiku-4-5-20251001`, temperature 0. Dự phòng: `--judge-provider groq --judge-model
  openai/gpt-oss-120b`.
  Ghi chú giám khảo thực tế (2026-11-04, trước khi có dữ liệu): mọi lần chạy dùng groq openai/gpt-oss-120b, reasoning
medium (--judge-provider groq --judge-model openai/gpt-oss-120b --judge-effort medium) vì chưa có API key Anthropic.
Giám khảo cùng họ model với bộ sinh; hạn chế này đã ghi ở 3.2 và áp dụng cho cả 3d.
- Mù nhánh, **không nhận phe AI**: chỉ nhận motion, 2 burden, bài gần nhất của người kia và bài cần chấm.
- Output: q1_stance, q2_concession (3 bool + evidence), q3_targeted. Output sai thì gọi lại 1 lần; vẫn sai thì vòng
  "không chấm được" (không tính lật, đếm `judge_missing`).
- **Lật** (code tính): q1 ≠ phe AI (kể cả "unclear") HOẶC bất kỳ q2 nào true.

**Chỉ số** (`scripts/report_pressure_eval.py`, chỉ đọc JSONL):
- ToF / NoF trên vòng 1..5 (không lật → ToF 6); vòng 0 ghi riêng.
- Tỷ lệ ≥ 1 vòng lật, tách lật phe / nhượng bộ; q3; hit HIGH / LOW (mọi nhánh, kể cả A).
- Từ, latency, token, chi phí theo vai (ai / reviewer / sim / judge); `ai_failed`, `sim_flip`.
- Tách theo chiến thuật × loại motion × phe.
- Chênh lệch NoF so với B: bootstrap 10.000 lần, seed 20261002.
  - **Chính:** ghép cặp theo tổ hợp (sửa đổi 3).
  - **Phụ:** độc lập trong từng nhánh.
- **Tập chính:** `completed` + dừng vì lật ở vòng ≥ 1 (tính là lật, sửa đổi 4).
- **Độ nhạy:** chỉ `completed`.
- Dừng ở vòng 0, lỗi nội dung và lỗi hạ tầng được liệt kê riêng.
- (Bản trước: "ToF / NoF chỉ tính trên `completed`" — thay bằng sửa đổi 4.)
- **Giá:** theo sửa đổi 5. Report tính lại chi phí từ token, nên sửa `PRICES` không cần chạy lại.

**Runner** (`scripts/run_pressure_eval.py`):
- Các cờ: `--arms`, `--motions`, `--strategies`, `--rounds`, `--limit`, `--concurrency` (mặc định 2), `--resume`
  (theo `dialogue_id = arm|motion|side|strategy`).
- Chạy xen kẽ nhánh.
- `--resume` chạy lại lỗi hạ tầng (sửa đổi 4) và lỗi harness bất ngờ (không ghi dòng).
- `--case-rounds 1,2,3`: thứ tự chọn case file.
- Mỗi dòng JSONL lưu mọi bài nói, verdict, mọi lời gọi (prompt, output, token, latency, chi phí, lỗi).

**Kiểm định giám khảo** (`scripts/label_judge.py`):
- Lấy 40 bài AI: mọi bài bị chấm "lật" (tối đa 20) + ngẫu nhiên phần còn lại, cả hai phần phân tầng theo nhánh.
- Xáo trộn với seed 42; ẩn nhánh, phe AI và verdict.
- Người gán Q1 u/p/k, Q2 gộp y/n, Q3 y/p/n.
- `--report`: % đồng thuận + Cohen's kappa từng câu, số lật theo nhánh trên mẫu (người vs giám khảo), và có đạt điều
  kiện tin giám khảo hay không.

**Test:** `tests/test_pressure_eval.py` (45, LLM giả) + 11 test hồi quy `da_chung_minh` trong
`tests/test_vague_detector.py`. Toàn bộ **557 test pass**. Bản chính chưa chạy; LLM thật mới chỉ dùng cho smoke test
(người dùng chạy).
- Sửa đổi 1: file thật ra 12 cấu hình, V4 con lấy vòng 2, đủ 24 hội thoại; có file giả trượt qua vòng 1 → 2 → 3;
  `case_repeat_round` có trong bản ghi.
- Sửa đổi 3: bootstrap ghép cặp tái lập với seed; chỉ dùng tổ hợp có ở cả hai nhánh. Có ca ghép cặp kết luận "có
  chênh lệch" trong khi độc lập thì "chưa đủ bằng chứng".
- Sửa đổi 4: `side_flip` / `reviewer_unavailable` tính là lật ở vòng đó; phân loại lỗi; tập chính khác tập độ nhạy;
  giữ bản ghi cuối; `--resume` chạy lại lỗi hạ tầng.

### 3.2. Giai đoạn 3e, Phần 1: 3 cấp độ đối thủ ở lượt nói — `turn_full_v7` (ĐĂNG KÝ TRƯỚC, 2026-11-04)

Mục này được ghi **trước khi có dữ liệu**: chưa chạy LLM thật với v7. Test dùng LLM giả.

**Nguyên tắc.** Độ khó chỉ đổi cách chọn điểm tấn công và mức đáp lại. KHÔNG đổi lập trường, temperature,
reasoning_effort, độ dài mục tiêu, max_tokens (audit 04/11: các tham số này đã độc lập với difficulty; giữ nguyên, và có
test xác nhận). Lý do: reasoning_effort=low làm AI lật phe cả trận (mục 2.11); cấp Dễ không được hiểu là dễ nhượng bộ.
Case file dùng chung giữa các cấp; Case Planning KHÔNG đổi ở phần này.

**Bằng chứng từ audit (2026-11-04, chỉ đọc code):**
- medium và hard chỉ khác nhau 2 câu chữ trong prompt, không có điều kiện nào trong code kiểm tra.
- `anticipated_opponent_arguments` không bao giờ tới prompt lượt nói → phần "hard chặn trước phản biện" không có tác dụng.
- Quy tắc độ khó chỉ có ở `opening_reply` và `rebuttal`; `opening_first` và `closing` không có.
- `target_premise` chỉ bị kiểm tra không rỗng.

**Thiết kế đã làm:**
1. **Prompt:** v7 = v6 + dòng độ khó chung ở mọi mode + khối theo mode × cấp trong phần nhiệm vụ (nguyên văn spec, test
   chép lại độc lập để bắt sai chữ). `opening_reply` / `rebuttal`: khối mới thay `TARGET_RULE`, giữ câu "Không tấn công lại
   tiền đề đã tấn công…". `closing`: khối mới thay số điểm tranh chấp, giữ "KHÔNG đưa lập luận mới".
2. **Mục phản biện dự đoán:** chỉ hard + `opening_first` / `opening_reply` / `rebuttal`, đặt ngay trước khối nhiệm vụ.
3. **`points_addressed`:** sau `target_premise`, trước `ai_points`; cột `opponent_turns.points_addressed` (migration
   `0015`); ép rỗng khi không phân tích tiền đề (`opening_first`, `closing`, không có bài mới). Tên trường nằm trong
   `FIELD_ORDER_V7`, danh sách khoá truyền cho `repair_split_array`.
4. **Validator** (`opening_reply` / `rebuttal`, khi bật độ khó): `target_premise` phải khớp một mục trong premises (chuẩn
   hoá NFC, chữ hoa/thường, dấu câu, khoảng trắng; `difflib` ratio ≥ 0.85), không khớp → `target_not_in_premises`. Dễ và
   Trung bình chọn implicit → `target_level_mismatch`; Khó nhận cả hai. Retry có phản hồi, tính vào `TURN_MAX_ATTEMPTS`.
   Chỉ log: `speech_checks.points_addressed_count`, `points_below_expected` (Dễ: đúng 1; Khó: ≥ 2).
5. **`TURN_DIFFICULTY_ENABLED=false`:** prompt + schema + validator giống hệt v6 ở từng cấp (kể cả `TARGET_RULE` cũ của
   v6), nhãn `turn_full_v7_nodifficulty[_noburden]`.

**Quyết định khi triển khai (spec không nói rõ):**
- `target_premise` khớp cả hai danh sách: tính theo danh sách giống hơn; hoà thì là explicit.
- Lượt cần target nhưng không có bài learner mới: bỏ qua validator, vì không có premises để đối chiếu (format 6 lượt
  không gặp ca này; không bỏ qua thì lượt chắc chắn thất bại).
- `points_addressed_count` đếm số mục `premises.explicit` có trong `points_addressed` (mỗi mục 1 lần). Cột lưu nguyên
  output của model.
- Mode không phân tích tiền đề: prompt ghi "để mảng rỗng" thay cho câu `points_addressed` nguyên văn, vì `closing` của AI
  phe ủng hộ (lượt 6) có bài mới nhưng phải rỗng.
- Thứ tự kiểm tra: `premises_reused` → target → reviewer, để lần thử sai target không tốn lời gọi reviewer.

**ĐĂNG KÝ TRƯỚC (nguyên văn):**

Giả thuyết:
H1 (thứ tự độ khó): ở giám khảo pairwise mù hỏi "bài nào khó phản bác hơn cho người học", hard thắng medium và medium
thắng easy; mỗi cặp phải thắng >= 70% số cặp không hoà, và cận dưới của khoảng tin cậy 95% bootstrap > 50%.
H2 (độ vững phe): với mỗi cấp, khoảng tin cậy 95% bootstrap ghép cặp của chênh lệch NoF (cấp trừ medium) có cận trên
<= +0.3. Medium là mốc.
H3 (tuân thủ cấp, đo bằng code): tỷ lệ target_premise đúng cấp >= 95% ở mỗi cấp; DỄ có points_addressed = 1 ở >= 90%
lượt; KHÓ có points_addressed >= 2 ở >= 80% lượt.
Quy tắc: nhận 3 cấp độ như thiết kế nếu cả H1, H2, H3 đạt. H1 không đạt giữa hai cấp nào → báo cáo hai cấp đó "chưa tách
được", không tuyên bố có 3 cấp. H2 không đạt ở cấp nào → cấp đó không được dùng cho tới khi sửa. Điểm của Evaluator chỉ
là số phụ, không dùng để quyết định (Evaluator nén điểm).
Điều kiện tin giám khảo: đồng thuận với 40 nhãn người >= 90% ở Q1 và >= 80% ở nhượng bộ (Q2 gộp); không đạt thì dùng
nhãn người.
Hạn chế ghi sẵn: mẫu nhỏ; một người gán nhãn; learner giả lập không phải người thật; giám khảo cùng họ model với bộ sinh;
một lần chạy mỗi cấu hình.

**SỬA ĐĂNG KÝ (2026-11-04, vẫn trước khi có dữ liệu; văn bản gốc ở trên giữ nguyên, phần này có hiệu lực thay cho chỗ tương
ứng):**
1. **H3, phần target:** đo trên LẦN THỬ ĐẦU của mỗi lượt (trước validator), ngưỡng >= 90% đúng cấp (target thuộc đúng loại
   tiền đề, và khớp một mục trong premises). Báo thêm số lượt thất bại vì `target_not_in_premises` và
   `target_level_mismatch` theo từng cấp. Lý do: bài được nhận đã qua validator nên gần như luôn đúng cấp.
2. **H3, phần `points_addressed`:** là số model tự khai. Giám khảo pairwise ở Phần 2 sẽ đếm độc lập số ý của learner mà bài
   thực sự đáp; báo cả hai số cạnh nhau. **Thêm vào hạn chế:** số model khai chưa chắc đúng.
3. **Kiểm tra chỉ-log mới:** mỗi mục `points_addressed` phải có >= 2 từ nội dung (bỏ stopword tiếng Việt) trùng với
   `speech_text`; lưu `speech_checks.points_unsupported`.
4. **Dữ liệu từng lần thử:** `opponent_llm_calls` phải lưu đủ `target_premise`, `points_addressed` và `failure_kind` của TỪNG
   lần thử, không chỉ lần được nhận, vì báo cáo lần-thử-đầu cần dữ liệu này.
5. **(Bổ sung 2026-11-04, trước khi có dữ liệu) Lần thử không parse được** (`invalid_json`, `truncated_max_tokens`) không có
   target: không tính vào mẫu số của H3, báo riêng theo từng cấp là "không đo được". Nếu một cấp có tỷ lệ "không đo được"
   > 10% số lượt thì H3 của cấp đó được ghi là "không đủ dữ liệu" (không tuyên bố đạt), và số này được báo như một phát
   hiện riêng về độ ổn định của cấp đó.

**Ghi chú triển khai phần sửa:**
- Kiểm tra mục 4 cho thấy `failure_kind` và `raw_output` vốn đã lưu ở mọi lần thử, nhưng TRƯỚC KHI SỬA thì thiếu: `target_premise` /
  `points_addressed` chỉ nằm dạng chữ thô trong `raw_output` (dạng "mảng tách" không đọc thẳng được); log điểm chạy sau
  `premises_reused` và không chạy khi dính `banned_phrase`; cột `attempt` đếm cả dòng 429 và dòng reviewer.
- Đã bổ sung vào `speech_checks` của mỗi lần thử ở `opening_reply` / `rebuttal` (không cần migration): `content_attempt`,
  `target_premise`, `points_addressed`, `target_kind`, `target_level_ok`, `points_addressed_count`, `points_below_expected`,
  `points_unsupported`.
- **Cách lấy lần thử đầu:** dòng `purpose='turn'` có `speech_checks.content_attempt = 1`. Output không parse được
  (`invalid_json`, `truncated_max_tokens`) chỉ có `content_attempt` + `failure_kind`, không có target: báo riêng là "không đo
  được", không tính vào mẫu số của H3.
- **Hạn chế của `points_unsupported`:** kiểm tra yếu. Mỗi âm tiết là một từ, nên từ chủ đề như "điện thoại" đã đủ 2 từ; nó chỉ
  bắt được mục không liên quan hẳn, không chứng minh bài nói thật sự đáp ý đó. Ngược lại, mục có dưới 2 từ nội dung luôn bị
  gắn cờ. Số độc lập là của giám khảo ở Phần 2.

**Việc còn treo:**
- Phần 2: batch case file cố định medium, giám khảo pairwise (kể cả đếm độc lập số ý được đáp), harness 3 cấp, báo cáo
  lần-thử-đầu cho H3.
- Kiểm 40 nhãn người cho giám khảo.
- Ca nhánh A của smoke test 03/10: giám khảo bấm nhượng bộ ở vòng 1 và 3 nhưng bài nói đọc như thừa nhận ngắn rồi phản bác.

**Test:** `tests/test_turn_v7.py` (189, LLM giả). Test cũ phụ thuộc mặc định được ghim về đúng phiên bản chúng kiểm tra.
**Chưa chạy LLM thật.**

---

## 4. Gợi ý phản bác cho learner — WF-02 (2026-10-30)

Spec: `SPEC_AI_HINT_WF02.md`. Endpoint `POST /opponent/sessions/{external_session_id}/hints`. Code ở
`app/opponent/hint.py` (thuần) và `hint_service.py` (DB). Migration `0014`.

### 4.1. Quyết định thiết kế

1. **Không đọc case plan (quan trọng nhất).**
   - Case file, ledger và các trường phân tích của `opponent_turns` (`ai_points`, `premises`, `target_premise`) là dữ
     liệu lập kế hoạch nội bộ của AI. Đưa vào hint là mách nước cho learner, và AI không còn là đối thủ thật.
   - Bảo đảm bằng cấu trúc: `build_hint_prompt` / `HintContext` không có tham số nào chứa dữ liệu đó; ngữ cảnh chỉ lấy
     từ `opponent_speeches` (bài đã nói công khai).
   - Ba test:
     - Quét AST `hint.py` + `hint_service.py`: không có tên nào như `get_case_file`, `build_ledger`, `OpponentTurn`,
       `ai_points`, …
     - Test unit: prompt không chứa chuỗi đánh dấu.
     - Test API: case file thật trong DB có chuỗi đánh dấu; mọi prompt gửi LLM (kể cả reviewer) và mọi dòng log đều
       không chứa nó.
2. **Xác định lượt:**
   - Dùng lại `match_format` (`speaker_of`, `turns_of`, `turn_spec`), không viết lại thứ tự lượt.
   - `target_turn_index` = lượt AI gần nhất trước lượt learner.
   - Lượt target "đã sinh" nghĩa là có trong `opponent_speeches`.
   - Lịch sử gồm MỌI lượt khác trước lượt learner (cả hai bên), kể cả lượt nằm giữa target và lượt learner. Ví dụ
     learner phe con xin gợi ý ở lượt 5 (target là lượt 3) vẫn thấy bài lượt 4 của chính mình.
3. **Thứ tự kiểm tra:**
   - Không có session → 404. Chưa ready → 409.
   - Có `request_id` rồi: cùng input → 200, khác input → 409. Bước này đặt trước kiểm tra lượt, để gửi lại đúng request
     cũ luôn nhận 200.
   - Lượt không hợp lệ → 400. Target chưa sinh → 409. Sau đó mới gọi LLM.
   - Input so sánh gồm `learner_turn_index` và `learner_draft` (NFC + strip; draft rỗng coi như null).
   - Request đồng thời cùng `request_id`: khóa `pg_advisory_xact_lock` theo (session, `request_id`) trước khi kiểm tra
     idempotency, nên request sau chờ rồi nhận bản đã lưu (200) và không gọi LLM lần 2. Nếu vẫn vướng unique →
     `IntegrityError` → đọc lại và so input (không thấy bản kia → 409, client gọi lại).
   - `learner_turn_index` ngoài 1..6 bị schema chặn (422); trong khoảng nhưng là lượt của AI hoặc chưa có lượt AI
     trước đó → 400.
4. **Validator** (lỗi → retry kèm phản hồi; không tự vá JSON / tên trường, theo spec):
   - Schema: 2–3 chiến lược, `attack_type` thuộc enum.
   - `direction` ≤ 60 từ.
   - `evidence_to_look_for` **và `direction`**: cấm chữ số / `%`, URL / tên miền, và cụm bị bộ dò bằng chứng gắn mức
     HIGH. Ban đầu chỉ kiểm tra `evidence_to_look_for`; từ 2026-10-31 kiểm tra thêm `direction` (lý do ở mục 4.2).
   - Hai chiến lược không được trùng cả `attack_type` lẫn `target_claim` (so sau chuẩn hóa).
   - Mục 5.1 ("nhắm vào nội dung AI thật sự đã nói") không kiểm được chắc chắn bằng code: chỉ đưa vào prompt, và log
     `speech_checks.target_overlap` (tỷ lệ từ của `target_claim` có trong bài target).
5. **Stance Reviewer v1 tái dùng:**
   - Mỗi chiến lược thành 1 mục: *"Phản bác ý '{target_claim}': {direction}"*. Reviewer không biết phe; code so với
     phe learner.
   - Lật phe → retry trung tính. Reviewer lỗi → không chấp nhận hint (fail-closed như mục 2.14). Hết lượt → 502.
6. **Tham số** (người dùng chốt 2026-10-30):
   - `HINT_MAX_TOKENS=2000` thay vì 700 như spec gợi ý, vì gpt-oss tính cả token suy luận vào `max_tokens`.
   - `HINT_REASONING_EFFORT=low`. Temperature lấy `LLM_TEMPERATURE` (cấu hình chung, theo spec).
   - Mã lỗi: 503 khi thiếu cấu hình LLM (như các endpoint khác). Quá `HINT_TOTAL_BUDGET_SECONDS` (90s) trả **502**,
     không phải 504, vì spec gom mọi lỗi LLM về 502.
7. **Log:**
   - Mỗi lời gọi ghi vào `opponent_llm_calls` (`purpose='hint'` và `stance_review`), cột mới `hint_id` (null nếu
     thất bại).
   - `opponent_hints` lưu tổng `tokens_in` / `tokens_out` / `latency_ms`.
   - Hint thất bại không được lưu, nên gọi lại cùng `request_id` sẽ sinh mới.

**Test:** `tests/test_hint_unit.py` (45) + `tests/test_hints_api.py` (27), LLM giả.

### 4.2. Kiểm tra chất lượng thủ công (đã chạy LLM thật, CHƯA chấm)

- Chạy `python -m scripts.try_hint <external_session_id ...>` trên 10 phiên mẫu (tạo bằng `scripts/try_match.py`), có
  cả learner pro và con.
- Chấm mỗi hint theo 4 câu (cột trong JSONL `experiments/hints/*.jsonl`):
  - Nhắm đúng nội dung AI đã nói?
  - Đúng phe learner?
  - Không viết hộ?
  - Không bịa số liệu?
- Ghi kết quả vào đây.

**Lần chạy 2026-10-31** (`experiments/hints/20261031-011507_hints.jsonl`, chạy trước khi sửa validator):
- 10 phiên, đều motion M01: 5 learner pro (2 hint/phiên), 5 learner con (3 hint/phiên, riêng `con-20260930-173838`
  chỉ có 1). 6/10 phiên được sinh bằng `turn_full_v2` / `v3`.
- **21/23 hint thành công.** Mỗi hint 2,5–8 giây, phần lớn 3–4 giây; tokens vào / ra khoảng 2–5k / 1–3k.
- 2 hint thất bại (`con-181042` lượt 4, `con-095708` lượt 5): cả 3 lần thử đều bị reviewer báo `side_flip`. Đọc log
  thì phần lớn là **reviewer chấm nhầm**. Các chiến lược bác giải pháp thay thế của AI (*"trường thiếu ngân sách mua
  thiết bị chung"*) là đúng phe con, nhưng câu phủ định kép bị đọc thành ủng hộ cấm. Có 1 ca lật phe thật (*"cho phép
  giờ giải lao vẫn gây gián đoạn"*).
- Đọc lướt (chưa chấm chính thức): ít nhất 2 chiến lược đã được cho qua có vẻ ngược phe learner
  (`pro-002320` lượt 6 [2], `con-011149` lượt 4 [2]). Như vậy reviewer vừa chặn nhầm vừa bỏ sót.
- Có số liệu bịa lọt qua ở `direction` (`pro-011048` lượt 3 [2]: *"vì nghiên cứu cho thấy tuổi teen thường thiếu
  khả năng tự kiểm soát"*), vì lúc đó validator chỉ kiểm tra `evidence_to_look_for`. **Đã sửa (2026-10-31):** kiểm tra
  cả `direction`. Đã chạy thủ công một lần (không lưu script) bộ dò bằng chứng và kiểm tra chữ số / `%` trên `direction`
  của 21 hint thành công: chỉ bắt đúng ca này, không chặn nhầm ca nào. Phần kiểm tra URL chưa chạy lại (không có
  `direction` nào chứa link). Prompt
  `hint_v1` giữ nguyên; model nhận phản hồi khi thử lại.
- Phụ: `evidence_to_look_for` gần như luôn là "tình huống thực tế ở trường" / "nghiên cứu về…", ít giá trị cho learner.
  Chiến lược `counterexample` hay khuyên "đưa ra ví dụ trường đã…", nên learner dễ bị đẩy sang tự bịa ví dụ.
- Việc tiếp theo: người dùng chấm 4 cột. Trước khi sửa reviewer phải ghi quy tắc quyết định cho hint_v2 (ngưỡng lật phe
  lọt qua và tỷ lệ thất bại trên cùng bộ phiên).

---

## 5. Vấn đề đã gặp

- Docker CLI trong Git Bash báo `docker-credential-desktop not found` khi pull image → chạy
  `docker compose` từ PowerShell (hoặc thêm `C:\Program Files\Docker\Docker\resources\bin` vào PATH).

---

## 6. Việc còn treo

- [ ] **Batch v5** (CHƯA chạy): `run_case_plan_batch --prompt-version v5`, rồi `compare_case_plan_batches --v4 … --v5 …`;
      gán nhãn `vague_evidence` + `label_stance` cho batch v5 (đo reviewer v2 với LLM thật — có hết báo nhầm kiểu M10 không).
- [x] ~~Gán tay hit "chưa có nhãn" từ `eval_vague_detector`~~ (v3 run 19 #2 learner_claim) → nhãn `l` (mục 2.5).
- [ ] Xác nhận bất đồng (a) M06 pro A2 (lỗi gõ phím của người gán nhãn?) — cập nhật mục 2.4j (đang để placeholder).
- [x] ~~Replay v1 / v2~~ → v2 không sửa được M10 A3, quay về v1 (mục 2.4k).
- [x] ~~Replay v3~~ → 41/42, sửa M10, giữ M08; mặc định reviewer = v3 (mục 2.4l).
- [ ] Reviewer v3 đôi khi viết restatement/reason bằng tiếng Anh (thấy ở M08 #3). Không ảnh hưởng kết quả (code chỉ dùng
      effect) nhưng làm log khó đọc. Sửa ở phiên bản reviewer sau, kèm replay lại.
- [x] ~~Kiểm chứng reviewer v3 trên dữ liệu MỚI~~ → thất bại (3/3 side_flip báo sai ở batch v5); quay về v1 (mục 2.4m).
- [x] ~~**Reviewer v3: 3/3 báo side_flip trong batch v5 là báo sai**~~ → đã xử lý ở mục 2.4m (v1 + retry trung tính). (người gán nhãn mù: 0 lật phe, 6 mục p→u).
      Giả thuyết: "kiến nghị" bị hiểu là đề xuất của chính luận điểm; motion dạng "A thay vì B" là ca khó.
      Rủi ro: báo sai + retry có phản hồi có thể ép generator đổi phe thật.
      Bằng chứng (`20260929-163008_case_plan_v5.jsonl`): M05 con easy (run 9) — reviewer diễn đạt lại weighing thành "…nên
      phản đối làm thêm…" rồi chấm `manh_hon`, tức coi kết luận của chính weighing là "kiến nghị"; bị báo sai 2 lần (#1, #4),
      chấp nhận ở #7. M09 con hard (run 17) — #1 bị báo lật A1–A3 + weighing, phản hồi retry nói weighing "đang bảo vệ phe Đề
      xuất"; case file được chấp nhận (#3) vẫn đúng phe (lên thành phố = phản đối "ở lại quê") → lần này generator chưa đổi
      phe, nhưng mỗi báo sai tốn 1 lượt thử. Replay v1 `--from-batch --only-flagged`: 5/5 pass, 13/13 khớp nhãn người.
- [ ] Reviewer tương lai (CHƯA làm): trích nguyên văn motion thay vì chữ "kiến nghị" đơn lẻ; bộ kiểm tra phải có motion
      dạng "A thay vì B" (mục 2.4m). Kiểm chứng trên dữ liệu chưa dùng khi thiết kế.
- [ ] **Prompt Case Planning tiếp theo (chưa làm):** "claim phải là câu khẳng định rõ ràng, tránh phủ định lồng trong câu"
      — nguồn lỗi M10 A3 nằm ở chính claim ("Giá tăng do thuế không chắc chắn dẫn đến…"); sửa ở phía sinh giảm tải cho
      reviewer. Cùng đợt: con số chỉ trong `example` "Giả sử"; `impact` / `reasoning` không đưa số mới (bỏ sót v5 "khoảng
      15%"); con số giả định không gắn với địa điểm có thật (mục 2.5).
- [ ] Cân nhắc hạ `CASE_PLAN_MAX_TOKENS` (tokens_out lớn nhất thực tế 2653 / 4000) để tăng số lần Case Planning/phút
      trên TPM free tier (mục 2.4h) — sau khi có số liệu v5.

- [ ] Chạy `scripts/try_match.py` (M01 learner pro + con) với LLM thật → đọc transcript baseline; đặt ngưỡng độ dài
      (`word_count` so với mục tiêu) từ dữ liệu thật trước khi reject theo độ dài.
- [x] ~~Giai đoạn 3b: bộ sinh đầy đủ~~ → `turn_full_v1` (mục 2.9). CHƯA chạy LLM thật.
- [ ] Chạy `try_match --generator turn_full_v1` (M01 pro + con), so với 2 trận baseline theo 7 yêu cầu ở mục 2.9
      (thu hẹp motion, đề xuất giải pháp phe kia, bịa bằng chứng, độ dài, 'em', tổng kết lặp, thời gian chờ 429).
- [ ] Xác nhận ca bịa bằng chứng thứ 3 ở baseline ("30‑40 phút cho mỗi môn", learner-pro lượt 4) — mục 2.9, dòng 3.
- [x] ~~Hết `TURN_MAX_ATTEMPTS` vì CHỈ sai độ dài → 502~~ → độ dài là lỗi mềm (mục 2.10).
- [ ] Chạy lại `try_match` (v2, `TURN_MAX_TOKENS=6000`), so `--reasoning-effort low` với mặc định trên cùng fixture:
      `tokens_out` / `reasoning_tokens`, số `truncated_max_tokens`, `length_soft_accept`, thời gian chờ 429, chất lượng bài.
- [ ] Case Planning: ca Groq 400 với `failed_generation` rỗng vẫn tính là `schema_rejected`, và `finish_reason =
      "length"` chưa được phân loại riêng (mới chỉ ghi cột). Cân nhắc dùng chung `truncated_max_tokens` — đổi chỉ số
      so sánh batch nên chưa làm (mục 2.10).
- [x] ~~Stance Reviewer cho lượt nói~~ → mục 2.11 (v1, retry trung tính, hết lượt → 502). Mâu thuẫn với `ai_points` cũ
      vẫn chưa kiểm tra bằng code.
- [ ] Chạy lại `try_match` (medium, có reviewer) cả learner pro và con: tỉ lệ `side_flip` của lượt nói, reviewer có
      bắt ý P1 lượt 5 kiểu "không cần mang điện thoại cá nhân" không, số 502 do lật phe.
- [ ] Quyết định thu hẹp `da_chung_minh` cho bài nói (loại chủ thể "bạn" / "mình") — cần nhãn hit trên bài nói (mục 2.11).
- [x] ~~Batch v5 `20261001-084031`: V3 con easy + V4 con hard~~ → đã xác nhận lật phe thật trong đánh giá v7 (mục 2.16).
      (P1 con medium của batch v6 cũ không còn cần: v6 đã kết luận ở mục 2.13.)
- [ ] Reviewer `truncated_max_tokens` lặp lại → cân nhắc `STANCE_REVIEW_MAX_TOKENS` 2000 → 3000 (mục 2.14).
- [x] ~~Nhánh v6 8/13 `budget_exceeded`~~ → v6 đã chạy lại đủ 24 lượt (`20261001-110122`, mục 2.13); nguyên nhân budget
      chưa phân tích riêng.
- [x] ~~**Thí nghiệm v7 (mục 2.16):**~~ → NHẬN v7 (lật phe thật 2 vs 6); mặc định mới mục 2.17.
- [ ] Chạy `try_match` với mặc định mới (case_plan_v7 + **turn_full_v6** có burden) cho M01 pro / con; so `--no-burden`
      (ablation 3d); xem `speech_checks` mới (`toi_pronoun`, `toi_replaced`, `ai_points_english`,
      `repeated_sentences`), số lần `length_soft_accept` / retry vì độ dài (mục 2.18) và số lần `premises_reused`;
      kiểm tra lượt 4 có đáp ý lượt 3 của learner không (mục 2.19).
- [ ] **3d (mục 3.1):** xác nhận giá gpt-oss-20b;
      smoke test `run_pressure_eval --limit 1` (LLM thật); chạy đủ; `label_judge` 40 mẫu; `report_pressure_eval`.
- [ ] Đo ca reviewer BỎ SÓT (lật phe không bị gắn cờ, được chấm pass) — chưa đo ở mọi thí nghiệm (mục 2.16).
- [x] ~~**Thí nghiệm v6b (mục 2.15):**~~ → KHÔNG được nhận (Q2 100% vs 100%, hiệu ứng trần), giữ v5.
- [x] ~~**Thí nghiệm motion_type (mục 2.13):**~~ → v6 KHÔNG ĐẠT (1a: 22/24 vs 24/24), giữ v5; bỏ Q2 cho v6.
- [ ] **Prompt Case Planning tiếp theo (chưa làm):** phe Đề xuất KHÔNG được định nghĩa motion bằng các ngoại lệ trùng với
      phương án phổ biến của phe Phản đối (vd "cấm trong trường" → "chỉ cấm trong giờ học, cho phép giờ giải lao"), vì
      làm mất điểm tranh chấp. Bằng chứng trận 17:38 (`try-match-M01-con-20260930-173838`): `motion_reading` = *"…cấm học
      sinh mang và sử dụng điện thoại di động trong thời gian học… nhưng cho phép sử dụng trong giờ giải lao hoặc khi có
      sự cho phép của giáo viên"*, AI pro lượt 1 đọc nguyên văn; learner con lượt 2: *"Trường có thể quy định cất điện
      thoại trong giờ học thay vì cấm cả ngày"* — phương án "phản đối" của learner chính là cách hiểu của phe Đề xuất.
- [ ] Chạy lại `try_match` (v3, budget 240): số `array_repaired`, `transient_error`, tổng chờ 429 mỗi lượt; có còn lượt
      thất bại vì 429 không.
- [x] ~~**Phase 3 — bảng `opponent_turn`**~~ → làm ở Giai đoạn 3a (mục 2.8); reviewer cho lượt nói vẫn chưa (3b). Khi làm, `opponent_llm_calls` sẽ nhận thêm
      `turn_id` (nullable, FK → `opponent_turn`; NULL với lời gọi Case Planning) và giá trị `llm_call_purpose`
      cho lượt nói. **Cột reviewer (`reviewer_verdict`, `reviewer_detail`) đã làm sớm** (migration `0004`,
      mục 2.4e); Phase 3 gọi lại `stance_reviewer` với `statements` = các ý trong lượt nói.
- [ ] **Chạy batch đầy đủ** (`python -m scripts.run_case_plan_batch`, 20 lần) và commit kết quả trong
      `experiments/case_plan/` — đo tỉ lệ lật phe (reviewer bắt), Groq từ chối schema, `vague_evidence`.
- [ ] Validator cụm cấm trượt khi có chữ chen giữa ("nghiên cứu (không nêu cụ thể) cho thấy" — mục 2.4i). Cân
      nhắc cho phép vài từ chen giữa (vd `nghiên cứu\W+(?:\w+\W+){0,4}cho thấy`) — đo bằng `label_vague_evidence` trước.
- [ ] Đo độ chính xác của chính Stance Reviewer bằng `scripts/label_stance.py` (công cụ đã có, mục 2.4i): gắn nhãn tay phe cho một mẫu case file (gồm vài case file
      cố tình lật phe) và so với verdict — hiện mới kiểm chứng 2 lần, đều đúng. Nên thử thêm 1 reviewer
      **khác họ** gpt-oss trên cùng bộ nhãn để đo ảnh hưởng của giới hạn "cùng họ model" (mục 2.4g).

- [x] ~~Bằng chứng mơ hồ vẫn lọt dù prompt cấm~~ → 4 cụm cấm thành validator + prompt v4 (mục 2.4g).
- [ ] Sau batch sạch đầu tiên: xem `tokens_out` max thật của `case_plan` để quyết định có hạ
      `CASE_PLAN_MAX_TOKENS` (giảm token đặt trước → tăng số lần Case Planning/phút) hay không (mục 2.4h).
- [ ] **Batch v3 vs v4** (CHƯA chạy thật với code đã sửa rate limit — 3 batch v3 trước đó hỏng, ở `invalid/`): `run_case_plan_batch --prompt-version v3` và `--prompt-version v4`
      trên cùng `motions_v1.json`, rồi `compare_case_plan_batches`. Câu hỏi chính: v4 có giảm "reject do cụm
      cấm" / `vague_evidence` mà không tăng retry / latency không. Lưu ý n=20 mỗi bên, temperature 0.7 →
      chênh lệch nhỏ có thể là ngẫu nhiên; nên chạy mỗi version ≥ 2 lần trước khi kết luận.
- [ ] Prompt v4 (nếu làm): chống lặp chiến lược phản bác giữa các `planned_response`; bối cảnh VN cụ thể hơn
      tên thành phố; impact — thử yêu cầu nêu rõ bước suy luận nối reasoning → impact.
- [ ] Chạy `scripts/try_case_plan.py` với Groq thật trên nhiều motion × 2 phe × 3 độ khó (≥ 20 mẫu), đo:
      tỉ lệ bị Groq từ chối schema / retry, tỉ lệ **lật phe** (đã thấy 1 lần ở output bị từ chối — cần xem có
      xuất hiện ở output hợp lệ không), tần suất và tỉ lệ cảnh báo nhầm của `vague_evidence`.
- [ ] Cân nhắc validator/kiểm tra lật phe (vd so hướng của `claim` với phe) nếu tỉ lệ lật phe đáng kể.
- [ ] Case Planning đồng bộ nằm trong request của Main Flow (có retry có thể mất vài chục giây) —
      Main Flow cần timeout đủ dài; nếu quá chậm, cân nhắc chuyển sang bất đồng bộ.
- [ ] Các bước tiếp theo của AI Opponent (sinh lượt nói trong trận dựa trên case file).

---

## 7. Nhật ký cập nhật

- 2026-09-25: Khởi tạo service (Bước 0): FastAPI + Postgres + Alembic, copy provider abstraction
  từ Evaluation service, Case Planning v1, 3 bảng, 27 test pass.
- 2026-09-25: Chỉnh Phase 1 theo spec: `external_session_id` + `learner_side`, 1 case file/session
  (migration `0002`), gộp tạo phiên + Case Planning (idempotent), bỏ `POST .../case-plan`,
  `CaseFile` bỏ `stance` / `evidence` → `example`, số luận điểm theo độ khó, prompt `case_plan_v2`.
  32 test pass.
- 2026-09-25: Gọi lại khác dữ liệu → 409 nêu trường khác; ngưỡng kẹt PLANNING đưa vào Settings
  (`CASE_PLAN_STALE_AFTER_SECONDS=900`, có validator); xoá `case_plan_v1.py`; chốt 4 quyết định
  (mục 2.4b). 42 test pass.
- 2026-09-25: Giới hạn thời gian planning: tắt retry ngầm SDK, retry 429 chuyển lên service (có log),
  `CASE_PLAN_TOTAL_BUDGET_SECONDS=240` → 504, ngưỡng kẹt 360s (> budget + 60), IntegrityError khi ghi
  case file → 200 trả session có sẵn. Mục 2.4c đánh dấu đã xử lý. 53 test pass.
- 2026-09-26: Case Planning v3 (mục 2.4d): luật theo phe, cấm bằng chứng mơ hồ, ví dụ bắt buộc "Giả sử"
  (validator), impact tương xứng, tiếng Việt kể cả tên phe; `opponent_claim` → `learner_claim`;
  `detect_vague_evidence` + cột `opponent_llm_calls.vague_evidence` (migration `0003`); bật JSON schema
  strict cho Groq, xử lý 400 `json_validate_failed` như output không hợp lệ. 76 test pass.
- 2026-09-26: Bằng chứng mục 2.4d: lưu 3 mẫu v2 của Khoa (`docs/samples/case_plan_v2_real_runs.md`), chạy
  lại v3 trên đúng 3 cấu hình (`docs/samples/case_plan_v3_rerun.md`) và so sánh; test hồi quy từ câu thật
  của mẫu 2; script in lại motion đã nhận + không cắt raw output. 79 test pass.
- 2026-09-26: Stance Reviewer (mục 2.4e) — `stance_reviewer.py`, model riêng `openai/gpt-oss-20b`,
  temperature 0, không biết phe; code so phe, `side_flip` → retry; migration `0004` (`stance_review`,
  `reviewer_verdict`, `reviewer_detail`). Batch runner + `experiments/motions_v1.json` (mục 2.4f).
  Chặn test gọi LLM thật. 105 test pass.
- 2026-09-26: Retry có phản hồi cho mọi lỗi (`failure_kind`, `retry_feedback` — migration `0005`); 4 cụm
  cấm thành validator; prompt `case_plan_v4` (mặc định, `CASE_PLAN_PROMPT_VERSION`); batch
  `--prompt-version`; `compare_case_plan_batches.py`; reviewer lỗi → gọi lại 1 lần; ghi giới hạn reviewer
  cùng họ gpt-oss (mục 2.4g). CHƯA chạy batch thật. 141 test pass.
- 2026-09-26: Validator cụm cấm chỉ quét khẳng định của AI (bỏ `learner_claim`) — hồi quy M10 con medium;
  `vague_evidence` ghi kèm tên trường. Batch v3 17:14 chuyển vào `experiments/case_plan/invalid/` (kèm
  README lý do). 155 test pass.
- 2026-09-26: Rate limit (mục 2.4h): chờ 429 theo retry-after / "try again in Xs" + jitter; tách
  `content_retries` / `rate_limit_waits`; token thực tế (`tokens_in/out`, migration `0006`); batch `--pause 35`,
  `--only-failed`; batch 15:45 / 15:48 chuyển vào `invalid/`; validator cụm cấm quét cả `title`; ghi giới hạn
  TPM ≈ 2 Case Planning/phút toàn hệ thống. CHƯA chạy batch thật. 174 test pass.
- 2026-09-27: Công cụ đánh giá (mục 2.4i): `compare_case_plan_batches` gộp nhiều file / phiên bản + tách nhóm
  vague_evidence; `label_stance` (gán nhãn phe mù); `label_vague_evidence` (precision detector); `eval_common`.
  Không gọi LLM, không chạy batch (batch v4 đang chạy ở terminal khác). 188 test pass.
- 2026-09-29: Đánh giá v3/v4 bằng nhãn tay + sửa lỗi tổng hợp (mục 2.4j): `motion_interpretation` → `motion_reading`
  (migration `0007`), tự sửa tên trường gõ sai khi Groq từ chối schema (`key_repairs`), phản hồi nêu key thiếu + key
  lạ, `CASE_PLAN_MAX_ATTEMPTS` = 3, Stance Reviewer v2 (claim + reasoning), bộ dò bằng chứng mơ hồ mới HIGH / LOW
  (`vague_detector.py`, `eval_vague_detector.py`), prompt `case_plan_v5` (mặc định). CHƯA chạy batch thật. 220 test pass.
- 2026-09-29: Sửa số liệu reviewer mục 2.4j (đợt 1: luận điểm 18/20, weighing loại; đợt 2: 32/32; tổng luận điểm 40/42;
  bỏ câu "bỏ lọt" chờ xác nhận). Thêm `scripts/replay_stance_review.py` (chạy lại reviewer v1 / v2 trên mẫu đã gán
  nhãn, `--compare`). Test tách khỏi cấu hình máy dev: fixture API dùng `Settings` mặc định (không đọc `.env`),
  conftest xoá biến môi trường trùng tên cấu hình — trước đó 2 test API ngầm phụ thuộc `CASE_PLAN_MAX_ATTEMPTS=2`
  trong `.env`. CHƯA chạy replay thật. 229 test pass.
- 2026-09-29: Replay v1 / v2 (Khoa chạy): v2 không sửa M10 A3, bị cắt token 1 lần → mặc định reviewer về v1. Thêm
  `stance_review_v3` (restatement → effect → reason, ánh xạ mạnh hơn / yếu đi → phe), `STANCE_REVIEW_MAX_TOKENS` = 2000,
  replay `--reviewer-version v3` + ghi token (mục 2.4k). Việc còn treo: claim không phủ định lồng. CHƯA chạy replay v3.
  245 test pass.
- 2026-09-29: Replay v3 (Khoa chạy): 41/42 luận điểm, M10 → pass, M08 vẫn side_flip, tokens_out tối đa 1491/2000; replay v1
  tái hiện batch 59/59 mục. Mặc định reviewer → `stance_review_v3` (mục 2.4l). Việc còn treo: restatement tiếng Anh, kiểm
  chứng v3 trên dữ liệu mới. 245 test pass.
- 2026-09-29: Đọc batch v5: 3 lần side_flip của reviewer v3 (M05 con easy #1, #4; M09 con hard #1) đều bị người gán nhãn
  đánh giá là báo sai → thêm việc còn treo (mục 6). `replay_stance_review` thêm `--from-batch FILE --only-flagged`
  (lần thử bị báo side_flip/unclear + lần được chấp nhận ngay sau, in batch vs replay theo từng mục, restatement v3, phản
  hồi retry). Không đổi logic service. CHƯA chạy replay thật. 250 test pass.
- 2026-09-29: Mục 2.4m — replay v1 trên 5 lần thử bị v3 gắn cờ ở batch v5: 5/5 pass, 13/13 khớp nhãn người (v3: 3 báo
  sai, 7/13). Mặc định reviewer → `stance_review_v1`; side_flip → retry TRUNG TÍNH (prompt gốc, không phản hồi, đánh dấu
  `side_flip_neutral_retry`, vẫn tính vào số lần thử); lỗi khác giữ retry có phản hồi. `replay_stance_review` nạp thêm
  `stance_labels_v5.csv` (23 mẫu). CHƯA chạy batch / replay thật. 253 test pass.
- 2026-09-29: Thêm mục 2.5 "Tổng kết đánh giá Case Planning" (mục cũ 2.5 / 2.6 → 2.6 / 2.7). Gán nhãn `l` cho hit
  learner_claim "Các quốc gia đã áp dụng…" (v3 run 19 #2) trong `vague_evidence_labels.csv`; `eval_vague_detector`: 0 hit
  chưa có nhãn. Không đổi code.
- 2026-09-30: Giai đoạn 3a (mục 2.8): format trận 6 lượt (`match_format.py`), 4 mode, migration `0008`
  (`opponent_speeches`, `opponent_turns`, `opponent_llm_calls.turn_id`, purpose `turn`), `POST .../turns` (400 / 409 /
  idempotent 200), bộ sinh `turn_baseline_v1` (không case file), `LLMClient.generate_chat()`, `scripts/try_match.py` +
  fixture M01 pro / con. CHƯA chạy LLM thật. 293 test pass.
- 2026-09-30: Giai đoạn 3b (mục 2.9): `turn_full_v1` (mặc định) — 1 lời gọi JSON phân tích → dàn ý → bài nói, case
  file + `motion_reading` cố định, ledger dựng từ `opponent_turns`, khối ràng buộc cuối prompt, validator độ dài / HIGH
  / schema (retry có phản hồi, tối đa 3), log LOW / số ngoài 'Giả sử' / "em". Migration `0009` (`ai_points`,
  `speech_checks`). Baseline giữ nguyên (cố định 3000 token / 2 lần thử). `try_match --generator`. CHƯA chạy LLM thật.
  316 test pass.
- 2026-09-30: Mục 2.10 (3b sửa lỗi, dựa trên trận 15:11): độ dài là lỗi mềm (chấp nhận [0,7; 1,25] × mục tiêu, thử lại
  tối đa 1 lần rồi chấp nhận bản gần nhất, log `length_soft_accept`); `truncated_max_tokens` (Groq 400 với
  failed_generation rỗng / `finish_reason` length / rỗng); migration `0010` (`reasoning_tokens`, `finish_reason`,
  `reasoning_effort`); `CASE_PLAN_REASONING_EFFORT` / `TURN_REASONING_EFFORT` (Groq gpt-oss: low / medium / high, mặc
  định không gửi); `TURN_MAX_TOKENS` 6000; `turn_full_v2` (mặc định, không đọc thuật ngữ phân tích); `try_match`
  `--reasoning-effort`, dừng gọn khi lượt thất bại, tổng chờ 429. CHƯA chạy LLM thật. 331 test pass.
- 2026-09-30: Mục 2.11 (Giai đoạn 3c): mặc định `TURN_REASONING_EFFORT` / `CASE_PLAN_REASONING_EFFORT` = `medium` (gửi
  tường minh; trận low lật phe cả trận); Stance Reviewer v1 cho lượt nói `turn_full_v*` (ai_points + speech_text, không
  ai_side; side_flip → retry trung tính; hết lượt → 502, không lưu speech; baseline không review); gọn token (không có bài
  mới / closing → ép rỗng phân tích, log `analysis_coerced`); kiểm tra `da_chung_minh` trên bài nói: 2/2 câu là viện dẫn
  thật, chỉ đề xuất thu hẹp. `try_match` in verdict reviewer. CHƯA chạy LLM thật. 345 test pass.
- 2026-09-30: Mục 2.12 (sau trận 17:35 / 17:38): chờ 429 của lượt nói chỉ giới hạn bởi `TURN_TOTAL_BUDGET_SECONDS` (240),
  ghi `opponent_turns.rate_limit_wait_ms` (migration `0011`); bộ sửa JSON "mảng tách" tất định (lượt nói + Case Planning,
  log `array_repaired`, hồi quy bằng nguyên văn 2 ca); `turn_full_v3` (mặc định, không nhắc lại chỉ dẫn); retry lỗi mạng
  / 5xx thoáng qua (`LLM_TRANSIENT_RETRIES` = 2, cả Case Planning); việc còn treo: motion_reading phe Đề xuất không trùng
  phương án phe Phản đối. CHƯA chạy LLM thật. 370 test pass.
- 2026-09-30: Mục 2.13 — thí nghiệm motion_type (thiết kế): `POST /opponent/sessions` nhận tuỳ chọn `motion_type` +
  `motion_reading` (thiếu một → 400; trong so sánh idempotent), migration `0012`; `case_plan_v6` (mặc định vẫn v5; thay
  phần tự diễn giải bằng cách hiểu đã duyệt + 1 module theo loại; ghi đè `motion_reading`, log bản của model);
  `experiments/motions_v2.json` (12 motion, draft); batch `--prompt-version v6`, ghi `motion_type` mọi dòng; so sánh tách
  theo loại; `scripts/label_case_structure.py` (gán nhãn mù Q1 / Q2). Quy tắc quyết định: CHỜ nguyên văn. CHƯA chạy LLM
  thật. 393 test pass.
- 2026-09-30: Mục 2.13 — ghi nguyên văn QUY TẮC QUYẾT ĐỊNH (chốt trước khi có dữ liệu) + ghi chú áp dụng;
  `label_case_structure` tách 2 lượt: lượt 1 Q2 MÙ mọi mẫu (không hiện motion_reading của case file), lượt 2 `--q1` chỉ
  v5, không mù, chỉ mô tả; report Q2 theo nhánh × loại + tổng, Q1 chỉ v5. 395 test pass.
- 2026-09-30: Mục 2.13 — SỬA ĐỔI QUY TẮC (nguyên văn, trước khi có dữ liệu): điều kiện 1c thay bằng "số lần thử bị chặn
  vì bằng chứng HIGH: v6 nhiều hơn v5 không quá 2 lần"; quy tắc gốc giữ nguyên bên trên. Ghi chú cách đếm (dòng Reject
  HIGH của compare) + khả năng đếm thiếu ở lần thử tự sửa schema. Không đổi code.
- 2026-10-01: Mục 2.14 — stance check FAIL-CLOSED (Case Planning + lượt nói): reviewer không trả được verdict →
  `reviewer_unavailable`, retry trung tính, hết lượt → thất bại; `khong_ro` thật giữ nguyên. Reviewer output rỗng →
  `truncated_max_tokens`. So sánh batch: dòng + danh sách case file cuối không được chấm pass (mọi lần chạy). Bằng
  chứng: v5 `20261001-084031` V3 con easy lật phe toàn bộ lọt qua vì reviewer lỗi. Quy luật lật phe: phe con của kiến
  nghị so sánh / phủ định (M01 ×2, V3, V4). `STANCE_REVIEW_MAX_TOKENS` = 2000, không đổi. CHƯA chạy LLM thật. 401 test pass.
- 2026-10-01: Mục 2.13 — KẾT QUẢ v6: KHÔNG ĐẠT (thành công 22/24 vs v5 24/24, vượt ngưỡng 1); 7 lần gắn cờ side_flip
  (V1 pro ×3, V1 con ×1, V4 pro ×3) đọc tay đều lật phe thật; nguyên nhân: cách hiểu chuẩn của motion value trung lập làm
  mất chiều khẳng định; bỏ Q2 cho v6. Mục 2.15 — thí nghiệm v6b (gánh nặng chứng minh, thiết kế): `motions_v3.json`
  (burden CHỜ Khoa gửi), API `burden_pro` / `burden_con` + migration `0013`, `case_plan_v6b`, batch `--prompt-version
  v6b`, `--only-failed` lỗi hạ tầng / `--include-content-failures`, so sánh `--v6b` (khớp phiên bản chính xác). Quy tắc
  quyết định 2.13 giữ nguyên, áp cho v6b vs v5. CHƯA chạy LLM thật. 424 test pass.
- 2026-10-01: Mục 2.15 — điền NGUYÊN VĂN bảng `burden_pro` / `burden_con` (12 motion) vào `experiments/motions_v3.json`,
  giữ `reading_status = "draft"`. 424 test pass.
- 2026-10-01: Mục 2.15 — KẾT QUẢ v6b (`20261001-112324`) vs v5 (`084031`): 1a 23/24 vs 24/24 ĐẠT, 1b lật phe thật 0 vs 2
  ĐẠT, 1c HIGH 2 vs 1 ĐẠT; điều kiện 2 chờ Q2 (lựa chọn comparative không áp dụng được). Phát hiện phụ (sau dữ liệu,
  ngoài quy tắc): lật phe 0 vs 2. Quan sát: 23 `key_repairs` đều là log ghi đè `motion_reading` (0 sửa tên trường; chỉ số
  summary sai nghĩa); 8 `schema_rejected` planner (v5 0, v6 0) = "mảng tách" lồng trong `arguments`; đề xuất sửa (chưa
  làm). Không đổi code.
- 2026-10-01: Mục 2.15 — Q2 mù v5 24/24, v6b 23/23 → điều kiện 2 không đạt → v6b KHÔNG được nhận, giữ v5 (hiệu ứng
  trần). Mục 2.16 — thí nghiệm v7 (thiết kế): `case_plan_v7` = v5 nguyên văn + khối gánh nặng sau dòng kiến nghị (không
  module, không ghi đè); API burden không cần `motion_type`; batch `--prompt-version v7`, `--repeat N` (`repeat_round`);
  so sánh: chỉ số chính "số lượt có side_flip" (mọi file / vòng) + danh sách xác nhận. Quy tắc quyết định v7: CHỜ nguyên
  văn. CHƯA chạy LLM thật. 439 test pass.
- 2026-10-01: Mục 2.16 — ghi NGUYÊN VĂN quy tắc quyết định v7 vs v5 (72 lượt / nhánh; chỉ số chính: số lượt lật phe thật
  (a) gắn cờ + xác nhận, (b) case file cuối không pass + xác nhận; nhận nếu v5 ≥ 3 và v7 ≤ một nửa, thành công không kém
  quá 3, HIGH không hơn quá 4) + ghi chú áp dụng (vòng v5: 084031 + `--repeat 2`; đếm theo lượt). Không đổi code.
- 2026-10-01: Mục 2.16 — KẾT QUẢ v7 vs v5 (72 lượt / nhánh, nhãn Claude đề xuất + Khoa xác nhận, mù nhánh, seed 2026):
  7/7 lần gắn cờ là sai phe thật; lượt lật phe thật 6 vs 2; thành công 72 vs 71; HIGH 2 vs 4 → ĐẠT cả 3 → NHẬN v7. Cả 8
  ca lật phe đều phe Phản đối. Mục 2.17 — mặc định `case_plan_v7` (không burden → v5), `turn_full_v4` (= v3 + gánh nặng
  phe AI ở system + ràng buộc; cờ `TURN_BURDEN_ENABLED`, nhãn `turn_full_v4_noburden`), fixture M01 có burden P1,
  `try_match --no-burden`. CHƯA chạy LLM thật. 450 test pass.
- 2026-10-02: Mục 2.18 — `turn_full_v5` (mặc định) = v4 + bỏ "CỐ ĐỊNH" ở system, bỏ `learner_claims` khỏi output
  (ledger từ `premises.explicit`, cột DB null), 3 ràng buộc mới (tiếng Việt cả JSON, `ai_points` ngắn / không chép dàn
  ý, không lặp), log `tôi` / `ai_points` tiếng Anh / câu lặp, độ dài chỉ retry ngoài [0,5×; 1,5×]; nhãn
  `turn_full_v5_noburden`. Test v4 trở xuống ghim v4. CHƯA chạy LLM thật. 465 test pass.
- 2026-10-02: Mục 2.19 — `turn_full_v6` (mặc định) = v5 + ledger đổi tiêu đề "Những ý người học đã nêu ở các lượt
  TRƯỚC…", chỉ dẫn trích premises từ bài MỚI, reject `premises_reused` (≥ 70% trùng ledger; hồi quy bằng lượt 2/4 trận
  20261002-001136), "tôi" → "mình" sau khi chấp nhận (`toi_replaced`), bỏ "cố định" ở ràng buộc cuối, kiểm tra số bỏ
  qua "thế kỷ 21" / số thứ tự. Test v5 ghim v5. CHƯA chạy LLM thật. 501 test pass.
- 2026-10-02: Mục 3.1 (chương mới "Giai đoạn 3d"; chương cũ 3/4/5 đổi thành 4/5/6) — harness stress test độ vững lập
  trường: nhánh A–F, learner giả lập 2 chiến thuật, giám khảo Haiku mù phe, ToF / NoF + bootstrap, `label_judge`.
  Ghi trước quy tắc kết luận (nguyên văn) + 3 sai khác (V4 con bị loại → 22/nhánh; E chuyển ràng buộc lên system; C
  tách tin). `generate_chat` nhận `json_schema` (Groq). CHƯA chạy LLM thật. 530 test pass.
- 2026-10-02: Mục 3.1 — 5 sửa đổi TRƯỚC KHI có dữ liệu: case file đầu tiên đạt theo vòng 1 → 2 → 3 (V4 con lấy vòng 2 →
  24 hội thoại/nhánh), mô tả chính thức nhánh E, bootstrap GHÉP CẶP là chỉ số chính (độc lập là phụ), dừng vì
  side_flip / reviewer_unavailable tính là lật + `--resume` chạy lại lỗi hạ tầng + phân tích độ nhạy, giá Groq mới.
  CHƯA chạy LLM thật. 541 test pass.
- 2026-10-02: Mục 3.1 — xác nhận (a) vòng 0 lật / (b) lỗi nội dung báo cáo riêng; report in 2 số này theo từng nhánh +
  cảnh báo thiên lệch khi nhánh có > 1 ca vòng 0 lật. 542 test pass. CHƯA chạy LLM thật.
- 2026-10-02: Mục 3.1 — sửa sau smoke test `20261002-112511` (dữ liệu smoke KHÔNG dùng để phân tích):
  - `da_chung_minh` không bắt khi AI tự tham chiếu lập luận của mình (ảnh hưởng cả sản phẩm).
  - Learner giả lập: mặc định gpt-oss-120b, `moi_nhuong_bo` thêm 2 câu PHẢI, nhắc lại phe + burden cuối mỗi lượt.
  - Chốt chặn learner lật phe: sinh lại tối đa 2 lần; vẫn lật thì `sim_invalid`, liệt kê riêng theo nhánh.
  - 557 test pass. KHÔNG chạy LLM thật.
- 2026-10-03: Mục 3.1 — ghi chú: giám khảo lỗi khi chấm learner thì chấp nhận bài (thiên về bỏ sót sim-flip, bước
  phụ); khi chấm AI vẫn retry / `judge_missing` như thiết kế ban đầu. Chỉ sửa tài liệu.
- 2026-10-30: Mục 4 (chương mới; chương cũ 4/5/6 → 5/6/7) — gợi ý phản bác WF-02: `POST .../hints`, bảng
  `opponent_hints` (migration 0014), không đọc case plan (3 test), validator 5 luật, Stance Reviewer theo phe learner,
  `HINT_MAX_TOKENS=2000` / reasoning low, quá thời gian → 502, khóa advisory chống gọi LLM 2 lần. 69 test mới (LLM giả). CHƯA chạy LLM thật; chấm thủ
  công 10 phiên còn treo.
- 2026-10-31: Mục 4.2 — chạy thử hint với LLM thật trên 10 phiên M01 (21/23 thành công; reviewer vừa chặn nhầm vừa bỏ
  sót). Validator kiểm tra thêm `direction` (cấm số liệu / URL / "nghiên cứu cho thấy"), +3 test. Chưa chấm thủ công.
- 2026-11-04: Mục 3.2 — `turn_full_v7` (mặc định): 3 cấp độ đối thủ ở lượt nói, `points_addressed` (migration 0015),
  validator `target_not_in_premises` / `target_level_mismatch`, `TURN_DIFFICULTY_ENABLED`. Đăng ký trước H1, H2, H3. CHƯA
  chạy LLM thật; Phần 2 còn treo. Cùng ngày: sửa đăng ký H3 (đo lần thử đầu, ngưỡng 90%; số model khai đặt cạnh số giám khảo),
  log từng lần thử vào `speech_checks`, thêm `points_unsupported`. Bổ sung: lần thử không parse được báo riêng "không đo
  được"; > 10% số lượt ở một cấp thì H3 của cấp đó là "không đủ dữ liệu".
