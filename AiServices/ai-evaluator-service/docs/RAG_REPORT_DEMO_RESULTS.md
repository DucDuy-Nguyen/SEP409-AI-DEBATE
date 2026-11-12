# Kết quả demo: kiểm chứng số liệu (RAG) trong báo cáo kết quả tranh biện (WF-01)

Tài liệu tóm tắt các bài kiểm tra D1–D6 của bước 4 (đưa kết quả kiểm chứng số liệu vào báo cáo kết quả), dùng cho Report 5.
Chi tiết kỹ thuật và lịch sử quyết định: `docs/AI_DEVELOPMENT_LOG.md` mục 3.22 và 3.23.

## 1. Luồng được kiểm tra

1. Người học nộp lượt nói cuối cùng. SystemService ghi nhận lượt, đóng phiên, rồi bắt đầu chấm **ở nền** và trả phản hồi ngay.
2. Chấm điểm: SystemService gọi AI Evaluator cho 3 vòng × 2 phe **song song**, sau đó tổng hợp 2 phe song song.
   Mỗi lượt của người học được kiểm chứng số liệu với kho dữ kiện đã duyệt (theo `Category` của chủ đề); phe AI không kiểm.
3. Kết quả lưu một lần duy nhất (`AIJudgement`). Mọi yêu cầu xem kết quả trong lúc đang chấm đều chờ đúng lần chấm đó.
4. Trình duyệt chuyển sang trang kết quả, hiện "Đang tổng hợp kết quả" cho tới khi có điểm, rồi hiện điểm và
   panel **Kiểm chứng số liệu**.

## 2. Môi trường

| Thành phần | Cấu hình |
|---|---|
| AI Evaluator | chạy local, `RAG_ENABLED=true`, LLM Groq `openai/gpt-oss-120b`, embedding bge-m3, kho fact pgvector (Docker) |
| SystemService | .NET 8 chạy local, DB SQL Server riêng cho demo `DebatePracticePlatformDB_RagDemo` (dựng từ model EF hiện tại) |
| Frontend | Vite dev server; ảnh chụp bằng Chrome headless (puppeteer) |
| Dữ liệu | 2 chủ đề: "Học thông qua chơi ở tiểu học" (Education, có kho fact) và "Mạng xã hội và giới trẻ" (Society, chưa có kho fact) |

Lập luận dùng trong demo được soạn sẵn; lượt của đối thủ AI được nộp qua API (không gọi dịch vụ AI đối thủ).

## 3. Kết quả

| Mã | Kịch bản | Kỳ vọng | Kết quả | Ảnh |
|---|---|---|---|---|
| D1 | Chủ đề Education. Người học nêu 1 số liệu đúng ("hơn 14.695 trường tiểu học") và 1 số liệu bịa ("tổng cộng 40 lớp tập huấn", nguồn ghi 115 lớp) | 1 Đúng nguồn, 1 Sai so với nguồn, kèm nguồn; điểm Evidence bị hạ | **Đạt.** 1 SUPPORTED, 1 CONTRADICTED; Evidence vòng mở đầu 3 → 1 | `rag_demo/d1_education_result.png` |
| D2 | Chủ đề Society | Báo cáo vẫn ra; panel "Chủ đề này chưa có kho dữ kiện đã duyệt" | **Đạt.** Cả 3 vòng `no_fact_base` | `rag_demo/d2_society_no_fact_base.png` |
| D3 | Tắt kho fact (Postgres) | Báo cáo vẫn ra; panel "Tạm thời không kiểm chứng được", không lộ lỗi kỹ thuật | **Đạt.** Cả 3 vòng `unavailable`; lỗi chỉ nằm trong dữ liệu thô và log | `rag_demo/d3_fact_store_down.png` |
| D4 | 5 phiên × 3 vòng: thời gian từ lúc nộp lượt cuối đến lúc có báo cáo, ngưỡng p95 ≤ 30 s | p95 ≤ 30 s | **Đạt.** p50 16,7 s, p95 20,2 s (bảng 3.1) | `rag_demo/d4_result_page_after_last_turn.png` |
| D5 | Tải lại trang kết quả (F5) và mở lại từ "Trận của tôi" | Điểm và panel vẫn hiện | **Đạt.** Cả hai cách đều đọc lại kết quả đã lưu | `rag_demo/d5_after_f5.png`, `rag_demo/d5_history.png`, `rag_demo/d5_from_history.png` |
| D6 | Phòng 1v1 (chủ đề Education), 2 người dùng mở kết quả gần như cùng lúc | 1 bản ghi kết quả; 2 bên cùng một kết quả; panel ở cả 2 bên | **Đạt.** 1 `AIJudgement`; người B mở kết quả lúc 1,5 s và nhận lúc 29,9 s (chờ đúng lần chấm đang chạy, không chấm lần hai); cả 2 bên có panel (A: 4 claim, B: 3 claim). Lần chạy trước cũng đạt (B nhận lúc 14,5 s) | `rag_demo/d6_p2p_user_a_pro.png`, `rag_demo/d6_p2p_user_b_con.png` |

Đường dẫn ảnh tính từ thư mục `docs/` này.

### 3.1. Thời gian (D4)

| Lần | Từ lúc nộp lượt cuối đến lúc có báo cáo |
|---|---|
| 1 | 16,7 s |
| 2 | 19,3 s |
| 3 | 15,7 s |
| 4 | 15,0 s |
| 5 | 20,5 s |
| **p50 / p95** | **16,7 s / 20,2 s** |

- Yêu cầu nộp lượt cuối trả về sau 0,6–1,0 s; thời gian còn lại là chấm điểm ở nền.
- Đo qua trình duyệt cho 1 phiên (gồm cả mở trình duyệt và đăng nhập): 24,5 s đến khi trang hiện đủ điểm và panel.
- Lần chấm đầu tiên sau khi khởi động SystemService (cold start): 23,3 s khi có bước khởi động sẵn (warm-up), so với 34 s trước khi có warm-up.
  Cold start không tính vào p95.
- Trước khi chuyển sang chấm nền (chấm trong yêu cầu nộp lượt cuối): p50 21,1 s, p95 26,4 s.

## 4. Giới hạn đã biết

- **Trích dẫn sai nguồn:** ở D1, nhãn CONTRADICTED đúng và lý do ghi "dự án có 115 lớp", nhưng nguồn được trích
  (fact e7279a4a) không chứa số 115; nguồn đúng là fact 2af92cb1. Sẽ sửa trong bước cải thiện prompt kiểm chứng và đo bằng
  chỉ số "citation accuracy" (tỷ lệ claim có nguồn trích chứa đúng chi tiết được xác nhận / phản bác).
- **Số khác có thể bị coi là "chi tiết thiếu"** thay vì "sai" (NOT_FOUND thay cho CONTRADICTED) ở một số lần chạy.
- Mỗi kịch bản chạy 1 lần (D4: 5 phiên); thời gian phụ thuộc độ trễ của Groq.
- Trong một lần chạy, SQL Server local phản hồi chậm hơn 30 s trong khoảng 1 phút ngay sau khi khởi động lại dịch vụ
  (chưa rõ nguyên nhân, không lặp lại ở 2 lần chạy sau): lần chấm nền của phiên đó lỗi và được ghi log, yêu cầu xem kết quả
  kế tiếp chấm lại đúng như thiết kế.
- Khóa "mỗi phiên chỉ chấm một lần" nằm trong bộ nhớ của SystemService: chỉ đúng khi SystemService chạy **1 replica**.
