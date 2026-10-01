# ADPP AI Evaluator Service

Module **AI giám khảo** của ADPP (AI Debate Practice Platform): nhận nội dung
tranh biện của learner, chấm điểm theo rubric 5 tiêu chí và trả về JSON có
giải thích chi tiết cho từng tiêu chí.

Đây là một **service HTTP độc lập** (FastAPI), chạy riêng, không nằm trong
backend chính. Frontend / backend khác gọi sang service này qua HTTP.

---

## 1. Kiến trúc: 3 cấp độ chấm điểm

| Cấp độ | Endpoint | Dùng khi nào | Điểm trả về |
|---|---|---|---|
| **Argument** | `POST /evaluate` | Chấm **1 lượt nói** riêng lẻ (kèm lượt gần nhất của đối phương nếu có) | `overall_score` (0–10) |
| **Round** | `POST /evaluate/round` | Chấm **cả 1 giai đoạn** (opening / rebuttal / closing) gồm nhiều lượt qua lại, có đánh giá thêm **tính nhất quán** của learner xuyên suốt giai đoạn | `round_score` (0–10) |
| **Session** | `POST /evaluate/session` | Tổng hợp **cả phiên** từ các kết quả Round đã chấm, ra báo cáo cuối phiên | `overall_score` (0–10) + điểm từng giai đoạn |

### Rubric 5 tiêu chí

`Logic`, `Evidence`, `Relevance`, `Structure`, `Persuasiveness` — mỗi tiêu chí
chấm 1–5, trọng số bằng nhau (20%). Định nghĩa đầy đủ ở
`app/prompts/evaluator_prompt.py` (`RUBRIC`).

### Điểm tổng luôn tính bằng công thức, không để AI tự cho

```
overall_score (Argument) = round_score (Round) = (tổng 5 tiêu chí / 25) × 10
```

Điểm tổng được **code tự tính** từ 5 điểm tiêu chí, không đọc con số điểm
tổng nào do LLM tự đưa ra. Lý do: đã thử cho AI tự chấm điểm tổng "cảm nhận",
kết quả không khớp người chấm thật hơn công thức mà lại kém ổn định (cùng 5
điểm tiêu chí nhưng điểm tổng dao động giữa các lần chạy). Chi tiết ở
`docs/AI_DEVELOPMENT_LOG.md` mục 3.8.

Ở cấp **Session**, `overall_score` là **trung bình cộng** các `round_score`
truyền vào (tính toán học, không gọi LLM chấm lại). LLM chỉ được dùng để viết
phần nhận xét tổng kết (`progress_trend`, điểm mạnh/yếu/gợi ý chung).

### Tự nhận biết có đối thủ hay không (SOLO / INTERACTIVE)

Tiêu chí `Relevance` bình thường bao gồm "phản biện đúng luận điểm đối
phương". Service **tự suy ra** có đối thủ hay không từ dữ liệu gửi lên — không
cần truyền thêm field nào:

- **Argument**: có `opponent_argument_text` → INTERACTIVE, không có → SOLO.
- **Round**: `turns` có ít nhất 1 lượt `speaker="opponent"` → INTERACTIVE,
  toàn `learner` → SOLO.

Ở chế độ SOLO, prompt bỏ hẳn yêu cầu "phản biện đối phương" để AI không bịa ra
một đối thủ không tồn tại. Lưu ý: việc này dựa vào **dữ liệu thực tế**, không
dựa vào `stage` — người nói thứ 2 ở giai đoạn opening vẫn có thể có nội dung
của đối phương để phản hồi.

### Cấu trúc thư mục

```
app/
  main.py                  # FastAPI app: /health, /demo, gắn router /evaluate
  config.py                # đọc .env, chọn LLM provider
  schemas.py               # Pydantic models: request/response của 3 cấp độ
  demo_page.py             # trang HTML thử nhanh endpoint /evaluate
  prompts/
    evaluator_prompt.py    # rubric + prompt cấp Argument, logic SOLO/INTERACTIVE
    round_prompt.py        # prompt cấp Round (tái sử dụng rubric ở trên)
    session_prompt.py      # prompt tổng hợp nhận xét cấp Session
  services/
    llm_client.py          # 1 interface chung cho 4 provider LLM
    json_utils.py          # parse JSON từ output LLM + retry dùng chung
    evaluator.py           # service cấp Argument
    round_evaluator.py     # service cấp Round
    session_evaluator.py   # service cấp Session
  routers/
    evaluate.py            # 3 endpoint POST
tests/                     # unit test chạy offline (không cần API key)
scripts/                   # công cụ nghiên cứu/validate (tốn API thật) — xem mục 6
docs/
  AI_DEVELOPMENT_LOG.md    # nhật ký quyết định thiết kế + lịch sử thay đổi
```

---

## 2. Cài đặt

Yêu cầu **Python 3.11 trở lên** (đã kiểm thử trên 3.11.9).

```bash
python -m venv venv
# Windows:
venv\Scripts\activate
# macOS / Linux:
source venv/bin/activate

pip install -r requirements.txt
```

> **Windows:** nếu `python -m venv venv` bị treo/lỗi với Python cài từ
> Microsoft Store, hãy cài Python bản chính thức từ python.org.

---

## 3. Cấu hình

```bash
cp .env.example .env          # Windows: copy .env.example .env
```

Mở `.env`, đặt `LLM_PROVIDER` thành **1 trong 4** giá trị sau và điền API key
tương ứng:

| `LLM_PROVIDER` | Biến cần điền | Ghi chú |
|---|---|---|
| `groq` *(mặc định)* | `GROQ_API_KEY`, `GROQ_MODEL` | Free tier, không cần thẻ — lấy key tại console.groq.com/keys |
| `gemini` | `GEMINI_API_KEY`, `GEMINI_MODEL` | Free tier, không cần thẻ — lấy key tại aistudio.google.com/apikey |
| `openai` | `OPENAI_API_KEY`, `OPENAI_MODEL` | Trả phí |
| `anthropic` | `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` | Trả phí |

**Không bao giờ commit file `.env`** (đã có trong `.gitignore`).

### ⚠️ Lỗi "model not found" với free tier

Groq và Gemini **đổi tên / khai tử model free khá thường xuyên** — một model
đang chạy tốt hôm nay có thể bị gỡ sau vài tuần (ví dụ `llama-3.3-70b-versatile`
trên Groq đã bị khai tử giữa chừng khi phát triển project này). Nếu gặp lỗi
404 / "model not found", **đừng sửa code** — kiểm tra model nào còn active rồi
sửa `GROQ_MODEL` / `GEMINI_MODEL` trong `.env`:

```bash
# Groq: liệt kê các model đang active
curl https://api.groq.com/openai/v1/models -H "Authorization: Bearer <GROQ_API_KEY>"
```

Với Gemini, xem danh sách model khả dụng tại aistudio.google.com.

Free tier cũng có **giới hạn tốc độ** (rate limit). Service đã tự chờ và thử lại
khi Groq trả lỗi 429, nhưng nếu gọi dồn dập vẫn có thể bị từ chối.

---

## 4. Chạy service

```bash
uvicorn app.main:app --reload
```

Service chạy ở `http://localhost:8000` (cổng mặc định của uvicorn; đổi bằng
`--port`). Các trang có sẵn:

- `http://localhost:8000/docs` — **Swagger UI**, gửi thử request cho cả 3 endpoint.
- `http://localhost:8000/demo` — trang HTML đơn giản để thử `/evaluate` bằng giao diện.
- `http://localhost:8000/health` — kiểm tra service sống và đang dùng provider nào.

Giá trị hợp lệ: `side` là `"pro"` hoặc `"con"`; `stage` là `"opening"`,
`"rebuttal"` hoặc `"closing"`; `speaker` là `"learner"` hoặc `"opponent"`.

### 4.1. `POST /evaluate` — chấm 1 lượt nói

```json
{
  "motion": "THBT mạng xã hội gây hại nhiều hơn lợi",
  "side": "pro",
  "stage": "rebuttal",
  "argument_text": "Mạng xã hội làm giảm thời gian tương tác trực tiếp giữa con người, dẫn đến suy giảm kỹ năng giao tiếp xã hội ở giới trẻ.",
  "opponent_argument_text": "Mạng xã hội giúp kết nối người ở xa nhau."
}
```

`opponent_argument_text` là tùy chọn — bỏ đi (hoặc để `null`) khi chấm một lượt
không có đối thủ (ví dụ lượt mở đầu của người nói đầu tiên).

Cấu trúc response (nội dung nhận xét do LLM sinh bằng tiếng Việt):

```json
{
  "overall_score": 4.4,
  "overall_reasoning": "Nhận xét tổng hợp ngắn về chất lượng lập luận ...",
  "criteria": [
    {"name": "Logic", "score": 2, "reasoning": "..."},
    {"name": "Evidence", "score": 1, "reasoning": "..."},
    {"name": "Relevance", "score": 4, "reasoning": "..."},
    {"name": "Structure", "score": 2, "reasoning": "..."},
    {"name": "Persuasiveness", "score": 2, "reasoning": "..."}
  ],
  "strengths": ["..."],
  "weaknesses": ["..."],
  "suggestions": ["..."],
  "raw_model_output": "..."
}
```

`raw_model_output` là output thô của LLM, chỉ để debug/audit — **không hiển
thị cho learner**.

### 4.2. `POST /evaluate/round` — chấm cả 1 giai đoạn

`turns` liệt kê các lượt nói **theo đúng thứ tự thời gian**; bắt buộc có ít
nhất 1 lượt của `learner`.

```json
{
  "motion": "THBT mạng xã hội gây hại nhiều hơn lợi",
  "side": "pro",
  "stage": "rebuttal",
  "turns": [
    {"speaker": "opponent", "text": "Mạng xã hội giúp kết nối người ở xa nhau."},
    {"speaker": "learner", "text": "Kết nối số lượng không đồng nghĩa chất lượng — 500 bạn Facebook không cứu được ai khỏi cô đơn lúc nửa đêm."},
    {"speaker": "opponent", "text": "Nhưng ít nhất còn hơn không có gì."},
    {"speaker": "learner", "text": "Vấn đề là nó tạo ảo tưởng đã đủ, khiến người dùng ngừng tìm kiếm kết nối thật, kết quả là cô đơn kéo dài hơn."}
  ]
}
```

Response giống cấp Argument, nhưng dùng `round_score` thay cho `overall_score`,
`consistency_note` (nhận xét tính nhất quán xuyên suốt giai đoạn) thay cho
`overall_reasoning`, và có thêm field `stage`.

### 4.3. `POST /evaluate/session` — báo cáo cả phiên

`rounds` là **danh sách kết quả đã nhận được từ `/evaluate/round`**, truyền
lại nguyên vẹn (backend lưu kết quả từng round, cuối phiên gửi gộp sang đây):

```json
{
  "motion": "THBT mạng xã hội gây hại nhiều hơn lợi",
  "side": "pro",
  "rounds": [
    {
      "stage": "opening",
      "round_score": 6.0,
      "criteria": [
        {"name": "Logic", "score": 3, "reasoning": "..."},
        {"name": "Evidence", "score": 2, "reasoning": "..."},
        {"name": "Relevance", "score": 4, "reasoning": "..."},
        {"name": "Structure", "score": 3, "reasoning": "..."},
        {"name": "Persuasiveness", "score": 3, "reasoning": "..."}
      ],
      "consistency_note": "Chỉ có một lượt nói, lập trường rõ ràng.",
      "strengths": ["..."],
      "weaknesses": ["..."],
      "suggestions": ["..."]
    },
    {
      "stage": "rebuttal",
      "round_score": 8.0,
      "criteria": [
        {"name": "Logic", "score": 4, "reasoning": "..."},
        {"name": "Evidence", "score": 4, "reasoning": "..."},
        {"name": "Relevance", "score": 4, "reasoning": "..."},
        {"name": "Structure", "score": 4, "reasoning": "..."},
        {"name": "Persuasiveness", "score": 4, "reasoning": "..."}
      ],
      "consistency_note": "Giữ vững lập trường, phản biện đúng từng lượt của đối phương.",
      "strengths": ["..."],
      "weaknesses": ["..."],
      "suggestions": ["..."]
    }
  ]
}
```

Response gồm `overall_score` (trung bình các `round_score`, ở ví dụ trên là
7.0), `stage_breakdown` (điểm từng giai đoạn, ví dụ `{"opening": 6.0,
"rebuttal": 8.0}`), `progress_trend`, `overall_strengths`,
`overall_weaknesses`, `overall_suggestions`.

### Mã lỗi

- `422` — request sai schema (thiếu field, giá trị `side`/`stage` không hợp
  lệ, `argument_text` rỗng, round không có lượt nào của learner...).
- `502` — LLM trả về kết quả không hợp lệ sau khi đã tự thử lại, LLM trả về
  nội dung rỗng, hoặc thiếu API key của provider đang chọn.
- `500` — các lỗi chưa được bắt riêng, ví dụ `LLM_PROVIDER` đặt sai tên, hoặc
  vẫn bị rate limit sau khi đã chờ và thử lại hết số lần cho phép.

---

## 5. Chạy test

```bash
python -m pytest tests/ -v
```

Hiện có **32 test** (4 test API, 15 test cấp Argument, 8 test cấp Round, 5 test
cấp Session). Tất cả chạy **offline** bằng `FakeLLMClient` (giả lập câu trả lời
của LLM) — **không cần API key, không tốn tiền**. Nên chạy lại mỗi khi sửa code.

> Trên Windows / PowerShell, dùng `python -m pytest` thay vì gọi `pytest` trực tiếp.

---

## 6. Thư mục `scripts/` — công cụ nghiên cứu / validate

Các script này **không cần để chạy service**. Chúng là công cụ đã dùng để kiểm
chứng chất lượng chấm điểm trong quá trình phát triển, **gọi API LLM thật (tốn
quota/chi phí)** và xuất kết quả ra file Excel. Chỉ chạy khi cần validate lại
sau khi sửa prompt/rubric.

| Script | Mục đích | Dữ liệu cần có |
|---|---|---|
| `run_batch_eval.py` | Chấm hàng loạt ở cấp Argument | `data/test_cases.json` |
| `run_session_batch_eval.py` | Chấm hàng loạt cấp Round + Session | `data/session_test_cases.json` |
| `run_ibm_agreement_eval.py` | So điểm AI với người chấm thật (IBM Project Debater) | Tự tải từ HuggingFace |
| `run_dagstuhl_agreement_eval.py` | So điểm AI với người chấm thật trên từng tiêu chí (Dagstuhl-15512) | Tải tay (xem dưới) |
| `run_language_consistency_check.py` | Kiểm tra AI chấm ổn định giữa tiếng Anh và tiếng Việt | `data/dagstuhl_processed.csv` |
| `run_reasoning_consistency_check.py` | Chấm cùng 1 bài nhiều lần, xuất toàn bộ nhận xét để đọc bằng mắt | `data/dagstuhl_processed.csv` |
| `compare_overall_score_methods.py` | So 2 cách tính điểm tổng — **không gọi API** | `dagstuhl_agreement_results.xlsx` |

Dữ liệu trong `data/` và file `.xlsx` kết quả **không được commit** (xem
`.gitignore`). Dataset Dagstuhl phải tải tay vì Zenodo chặn tải tự động:
tải `dagstuhl-15512-argquality-corpus-v2.zip` tại
`https://zenodo.org/records/3973285`, giải nén vào
`data/_dagstuhl_raw/extracted/`. Lần chạy đầu `run_dagstuhl_agreement_eval.py`
sẽ tự sinh `data/dagstuhl_processed.csv` cho 2 script consistency ở trên.

---

## 7. Tài liệu thiết kế

Muốn hiểu **vì sao** hệ thống được thiết kế như hiện tại (chọn rubric, đổi qua
lại cách tính điểm tổng, xử lý hallucination, kết quả so với người chấm thật...),
đọc `docs/AI_DEVELOPMENT_LOG.md`.

---

## 8. Tích hợp với Frontend / Backend khác

Service này chạy trên cổng riêng (mặc định `8000`). Bên gọi gửi HTTP `POST`
với body JSON tới 3 endpoint ở mục 4 và nhận lại JSON.

**Chưa có, cần bổ sung trước khi lên production thật** (không phải việc cần
làm ngay):

- **Xác thực giữa các service** — hiện tại ai gọi được tới cổng của service
  cũng dùng được (và tiêu quota LLM của nhóm).
- **CORS** — service chưa cấu hình CORS. Nếu Frontend gọi **trực tiếp từ trình
  duyệt** (khác origin), trình duyệt sẽ chặn request. Có 2 cách: gọi qua
  backend chính (server-to-server, không bị CORS), hoặc thêm `CORSMiddleware`
  của FastAPI vào `app/main.py`.
- **Thời gian phản hồi** — mỗi request gọi LLM thật, thường mất vài giây đến
  vài chục giây (timeout mặc định 60 giây, cấu hình bằng `LLM_TIMEOUT_SECONDS`).
  Phía gọi nên đặt timeout đủ dài và hiển thị trạng thái đang chấm.
