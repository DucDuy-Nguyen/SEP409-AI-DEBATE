# Batch bị loại — KHÔNG dùng cho báo cáo

Giữ lại để truy vết, không dùng để so sánh prompt.

| File | Lý do loại |
|---|---|
| `20260926-154557_case_plan_v3.*` | Hỏng do rate-limit TPM free tier (retry chờ cố định 3s), không dùng để so sánh. 9/20 lần chạy `llm_error` do Groq 429 (TPM 8000/phút, mỗi request xin ~4000 token; Groq yêu cầu chờ 7–25s). |
| `20260926-154800_case_plan_v3.*` | Hỏng do rate-limit TPM free tier (retry chờ cố định 3s), không dùng để so sánh. Chạy **song song** với batch 15:45 (chung hạn mức TPM), dừng ở lần chạy 11/20. |
| `20260926-171443_case_plan_v3.*` | Hỏng do rate-limit TPM free tier (retry chờ cố định 3s), không dùng để so sánh. 9/20 lần chạy `llm_error` do Groq 429. Ngoài ra M10 / con / medium bị validator cụm cấm reject **oan** (cụm nằm trong `learner_claim` — dự đoán lời learner), đã sửa: validator chỉ quét khẳng định của AI (dev log mục 2.4g). |

Đã sửa (dev log mục 2.4h): chờ 429 theo `retry-after` / "try again in Xs" + jitter; batch mặc định nghỉ 35s giữa
các lần chạy; tách `content_retries` / `rate_limit_waits`. Chạy lại các cấu hình `llm_error` bằng
`python -m scripts.run_case_plan_batch --only-failed <file>` nếu cần — nhưng batch mới đầy đủ vẫn là dữ liệu sạch hơn.
