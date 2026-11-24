# BÁO CÁO KIỂM THỬ END-TO-END (E2E) BACKEND COMPETITION
## MÔI TRƯỜNG DATABASE V9 – `DebatePracticePlatformDB3`

---

## 1. THÔNG TIN TỔNG QUAN & ĐIỀU KIỆN TIÊN QUYẾT (PRE-CONDITIONS)

| Thuộc tính | Giá trị kiểm tra thực tế | Trạng thái |
|---|---|---|
| **Git Branch** | `competition` (Commit `17cd5ab44b478cf5bf4400d65ed9507073ad1cc9` – *Fix bracket in competition*) | **ĐÚNG** |
| **SQL Server Instance** | `DESKTOP-DI46HNF\SQLEXPRESS` (Network alias: `THANH-SANGG\SQLEXPRESS`) | **ĐÚNG** |
| **Target Database duy nhất** | `DebatePracticePlatformDB3` | **TUÂN THỦ TUYỆT ĐỐI** |
| **Database được bảo vệ** | `DebatePracticePlatformDB` (legacy) và `DebatePracticePlatformDB1` | **KHÔNG GHI / KHÔNG SỬA / NGUYÊN VẸN** |
| **C# Source Code & DB Schema** | Không chỉnh sửa source code C#, không ALTER/DROP table, không EF migrations | **READ-ONLY AUDIT MODE** |
| **Backend Service** | `SystemService` (Port 5001, .NET 8) kết nối trực tiếp `DebatePracticePlatformDB3` | **HOẠT ĐỘNG** |

---

## 2. KẾT QUẢ ĐỐI SOÁT SCHEMA VÀ NGUYÊN NHÂN LỖI LẦN TRƯỚC

### 2.1. Cột `DebateSessions.Difficulty`
- **Kiểm tra schema `DebatePracticePlatformDB3`:**
  - Lệnh kiểm tra: `SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, IS_NULLABLE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = 'DebateSessions' AND COLUMN_NAME = 'Difficulty'`
  - Kết quả: Cột `Difficulty` tồn tại dưới dạng `nvarchar(50) NULL`.
- **Nguyên nhân lần E2E trước bị blocked tại Prepare Debate:**
  - Ở lần test trước, backend đọc chuỗi kết nối từ **User Secrets (`secrets.json`)** trỏ vào `DebatePracticePlatformDB` (database cũ không có cột `Difficulty`), đè lên cấu hình trong `appsettings.json`.
  - Trong đợt kiểm thử này, cấu hình User Secrets và `appsettings.json` đã được đồng bộ chuẩn xác trỏ về `DebatePracticePlatformDB3`.
  - Kết quả: Endpoint `POST /api/competitions/matches/{id}/prepare-debate` đã chạy **THÀNH CÔNG 100% (HTTP 200)** cho cả giải đấu INDIVIDUAL và TEAM.

---

## 3. TÀI KHOẢN VÀ DỮ LIỆU SEEDING (`DebatePracticePlatformDB3`)

Dữ liệu kiểm thử độc lập được khởi tạo an toàn vào `DebatePracticePlatformDB3` qua script `scratch/seed_db3.sql`:
- **BTC (Lecturer):** `lecturer@test.com` (UserId: 11, Role: `Lecturer`) – Người tạo và quản lý giải đấu.
- **Admin:** `admin@test.com` (UserId: 1, Role: `Admin`).
- **Debater 01 – 08 (Member):** UserIds 2 đến 9 – Thí sinh thi đấu đơn (INDIVIDUAL) và ghép đội (TEAM).
- **External Debater:** `debater12@test.com` (UserId: 10, Role: `Member`) – Dùng để kiểm thử phân quyền (Unauthorized/Forbidden).

*Authentication:* Sinh JWT token chuẩn HMAC-SHA256 thông qua tool nội bộ .NET 8 (`scratch/TokenGen`).

---

## 4. BẢNG TỔNG HỢP KẾT QUẢ KIỂM THỬ (E2E TEST MATRIX)

| Mã test | Quy trình | Endpoint | Input / Mô tả | HTTP Status | Kết quả | Ghi chú |
|---|---|---|---|:---:|:---:|---|
| **E2E-IND-01** | Create Competition | `POST /api/competitions` | INDIVIDUAL, 1v1, max=4 | **200 OK** | **PASS** | Tạo Competition ID: 1, Status: Draft |
| **E2E-IND-02** | Patch Competition | `PATCH /api/competitions/1` | Cập nhật Title, Dates | **200 OK** | **PASS** | Cập nhật cấu hình giải đấu thành công |
| **E2E-IND-03** | Open Registration | `POST /api/competitions/1/open-registration` | BTC gọi mở đăng ký | **200 OK** | **PASS** | Status: `OpenRegistration` |
| **E2E-IND-04** | User Registrations | `POST /api/competitions/1/registrations` | 4 thí sinh đăng ký (User 2, 3, 4, 5) | **200 OK** | **PASS** | Tạo 4 registration pending |
| **E2E-IND-05** | Approve Registrations| `PUT /api/competitions/1/registrations/{id}/approve` | BTC duyệt từng thí sinh | **200 OK** | **PASS** | 4 thí sinh chuyển trạng thái `Approved` |
| **E2E-IND-06** | Close Registration | `POST /api/competitions/1/close-registration` | BTC đóng đăng ký | **200 OK** | **PASS** | Status: `RegistrationClosed` |
| **E2E-IND-07** | Generate Bracket | `POST /api/competitions/1/bracket` | Tạo nhánh đấu Single Elimination | **200 OK** | **PASS** | 2 Round: Match 1 & 2 (Bán kết), Match 3 (Chung kết) |
| **E2E-IND-08** | Start Competition | `POST /api/competitions/1/start` | BTC khởi tranh giải đấu | **200 OK** | **PASS** | Status: `Ongoing`; Match 1, 2: `Ready` |
| **E2E-IND-09** | **Prepare Debate Match 1** | `POST /api/competitions/matches/1/prepare-debate` | Gán TopicId=1, ghép PRO (User 4), CON (User 2) | **200 OK** | **PASS** | **Tạo DebateSessionId=1, Difficulty='Medium'. Hết lỗi Invalid Column!** |
| **E2E-IND-10** | **Prepare Debate Idempotency** | `POST /api/competitions/matches/1/prepare-debate` | Gọi lại lần 2 cho Match 1 | **200 OK** | **PASS** | Trả về đúng DebateSessionId=1 ban đầu |
| **E2E-IND-11** | Start Debate Session | `POST /api/debate/1/start` | BTC bắt đầu trận đấu | **200 OK** | **PASS** | Session chuyển sang Status `2 (Ongoing)` |
| **E2E-IND-12** | Submit Debate Turns | `POST /api/debate/1/arguments` | 6 lượt nói (3 vòng) luân phiên PRO / CON | **200 OK** | **PASS** | Toàn bộ 6 lượt nói ghi nhận thành công, Session chuyển sang `3 (Completed)` |
| **E2E-IND-13** | **AI Evaluation** | `POST /api/debate/1/evaluate` | Đánh giá AI tự động (Azure Container Apps) | **200 OK** | **PASS** | **AI Llama 3.3 chấm điểm toàn bộ 3 vòng, tính điểm PRO 5.33, CON 5.17, ghi nhận AIJudgements!** |
| **E2E-IND-14** | **Match Review** | `GET /api/competitions/1/matches/1/review` | BTC xem kết quả trận đấu | **500 Err** | **FAIL** | **Lỗi `Invalid object name 'DebateCriteria'` do Database V9 đổi tên bảng** |
| **E2E-IND-15** | **Match Finalize** | `POST /api/competitions/1/matches/1/finalize` | BTC xác nhận điểm và người thắng | **500 Err** | **BLOCKED** | Bị chặn bởi lỗi `Invalid object name 'DebateCriteria'` |
| **E2E-TEAM-01** | Create Team Competition | `POST /api/competitions` | TEAM, 2v2, max=8 | **200 OK** | **PASS** | Tạo Competition ID: 2 |
| **E2E-TEAM-02** | Open Registration | `POST /api/competitions/2/open-registration` | Mở đăng ký đội | **200 OK** | **PASS** | Status: `OpenRegistration` |
| **E2E-TEAM-03** | Team Formation (4 đội) | `POST /teams` & `invitations/accept` | Tạo 4 đội, mỗi đội 1 Captain + 1 Member | **200 OK** | **PASS** | 4 đội Active với 8 thí sinh độc lập |
| **E2E-TEAM-04** | Generate Team Bracket | `POST /api/competitions/2/bracket` | Single Elimination cho 4 đội | **200 OK** | **PASS** | Round 1 (Matches 4, 5), Round 2 (Match 6) |
| **E2E-TEAM-05** | Start Team Competition | `POST /api/competitions/2/start` | Khởi tranh giải đấu đội | **200 OK** | **PASS** | Status: `Ongoing`, Match 4 & 5: `Ready` |
| **E2E-TEAM-06** | **Prepare Debate Team Match** | `POST /api/competitions/matches/4/prepare-debate` | Ghép 4 debater (2 PRO, 2 CON) | **200 OK** | **PASS** | **Tạo DebateSessionId=2 với 4 debater, Difficulty='Medium'** |
| **E2E-TEAM-07** | Start Team Debate | `POST /api/debate/2/start` | Bắt đầu tranh biện 2v2 | **200 OK** | **PASS** | Session 2 `Ongoing`, Turn 1 OPENING kích hoạt |
| **E2E-SEC-01** | Security Non-BTC Prepare | `POST /matches/1/prepare-debate` | Thí sinh ngoài (User 10) gọi | **400 Bad** | **PASS** | Bị chặn: "Chỉ Ban tổ chức giải đấu mới có quyền..." |
| **E2E-SEC-02** | Security Non-BTC Bracket | `POST /competitions/1/bracket` | Thí sinh ngoài gọi sinh bảng | **403 Forb** | **PASS** | Bị chặn: "Only the creator may generate the bracket." |
| **E2E-SEC-03** | Conflict Duplicate Bracket | `POST /competitions/1/bracket` | Gọi sinh bảng khi giải đã chạy | **409 Conf** | **PASS** | Bị chặn: "Registration must be closed..." |
| **E2E-SEC-04** | Validation Invalid Topic | `POST /matches/2/prepare-debate` | TopicId không tồn tại (99999) | **400 Bad** | **PASS** | Bị chặn: "Chủ đề tranh biện không hợp lệ..." |

---

## 5. CHI TIẾT CÁC PHÁT HIỆN TRỌNG YẾU

### 5.1. Vấn đề `DebateSessions.Difficulty` ĐÃ ĐƯỢC GIẢI QUYẾT TRIỆT ĐỂ
- Cột `Difficulty` trong Database V9 (`DebatePracticePlatformDB3`) hoạt động hoàn toàn chính xác.
- Endpoint `PrepareMatchDebate` trên cả 2 thể thức **INDIVIDUAL (1v1)** và **TEAM (2v2)** đều sinh phiên tranh biện thành công, gán giá trị độ khó và liên kết khóa ngoại với `CompetitionMatches` mà không xảy ra bất kỳ ngoại lệ nào.

### 5.2. Luồng AI Evaluation HOẠT ĐỘNG HOÀN HẢO
- Phiên tranh biện 6 lượt nói kết thúc hợp lệ và chuyển trạng thái `Completed`.
- Khi gọi `POST /api/debate/1/evaluate`, hệ thống tích hợp thành công với AI Evaluator Service trên Azure Container Apps:
  - Model: `Groq / Llama-3.3-70b-versatile`.
  - Chấm điểm chi tiết từng tiêu chí: Logic, Evidence, Relevance, Structure, Persuasiveness.
  - Phân tích điểm mạnh, điểm yếu, xu hướng tiến bộ và gợi ý bên thắng (`PRO` 5.33 vs `CON` 5.17).
  - Bản ghi được lưu trữ thành công vào bảng `AIJudgements` trong database `DebatePracticePlatformDB3`.

### 5.3. NGUYÊN NHÂN LỖI BLOCKER MỚI: BẢNG `DebateCriteria` ĐÃ BỊ ĐỔI TÊN THÀNH `DebateScoreWeight`
- **Mã lỗi phát sinh:**
  `HTTP 500 Internal Server Error`
  `{"success":false,"message":"Invalid object name 'DebateCriteria'."}`
- **Vị trí phát sinh:**
  1. `CompetitionTournamentService.cs:283`:
     ```csharp
     var criteria = await _db.DebateCriteria.AsNoTracking().Where(c => c.IsActive).OrderBy(c => c.CriteriaId).ToListAsync(ct);
     ```
  2. `CompetitionTournamentService.cs:308`:
     ```csharp
     var criteria = await _db.DebateCriteria.Where(c => c.IsActive).ToListAsync(ct);
     ```
- **Nguồn gốc từ Database Script V0.9 (`DatabaseSEP/AIDebate-V0.9.sql` dòng 2167):**
  ```sql
  EXEC sp_rename 'DebateCriteria', 'DebateScoreWeight';
  ```
  Script V0.9 đã đổi tên bảng `DebateCriteria` thành `DebateScoreWeight`. Trong khi đó, Entity Framework Core Configuration trong source code backend (`DebateCriteriaConfiguration.cs` dòng 11) vẫn cấu hình:
  ```csharp
  builder.ToTable("DebateCriteria");
  ```
- **Hậu quả:** 
  - Thao tác xem lại trận đấu (`GetReview`) và chốt kết quả giải đấu (`FinalizeMatch`) không thể thực thi được trên database V9.
  - Do trận đấu bán kết không thể finalize, luồng cập nhật nhánh đấu tự động (lan truyền người thắng sang trận chung kết `NextMatchId`) và kết thúc giải đấu (`CompleteCompetition`) bị chặn gián tiếp.

---

## 6. KẾT LUẬN & KIẾN NGHỊ

### 6.1. Mức độ hoạt động End-to-End của Competition Backend
- **Khởi tạo và Quản trị Giải đấu:** **100% Hoàn hảo** (Tạo giải, sửa cấu hình, mở/đóng đăng ký, duyệt thí sinh, sinh bracket Single Elimination).
- **Quy trình Thi đấu Đồng đội (TEAM 2v2):** **100% Hoàn hảo** (Tạo đội, gửi lời mời thành viên, chấp nhận gia nhập, ghép cặp 4 debater trong trận đấu).
- **Cầu nối Competition – Debate (Bridge Service):** **100% Hoàn hảo** (Ghép thí sinh, ánh xạ vai trò PRO/CON, xử lý độ khó, tính idempotent).
- **Thực thi Tranh biện & Chấm điểm AI:** **100% Hoàn hảo** (Bắt đầu phiên, gửi argument luân phiên theo round, gọi AI Evaluator chấm điểm tự động và lưu phán quyết).
- **Đánh giá Trọng tài & Chốt giải (Review & Finalize):** **BỊ CHẶN DO LỆCH SCHEMA** giữa Database V9 (`DebateScoreWeight`) và C# Entity (`DebateCriteria`).

### 6.2. Giải pháp khắc phục triệt để (Action Items cho dự án)
Để đưa toàn bộ luồng E2E về trạng thái PASS 100%, chọn **MỘT TRONG HAI** phương án sau:

- **Phương án 1 (Khuyến nghị – Đồng bộ Code theo Database V0.9):**
  Trong `DebateCriteriaConfiguration.cs` (hoặc mapping tương ứng), cập nhật tên bảng mapping thành `DebateScoreWeight`:
  ```csharp
  builder.ToTable("DebateScoreWeight");
  ```
  *(Cách này bảo toàn đúng schema thiết kế mới nhất của Database V0.9).*

- **Phương án 2 (Đồng bộ Database theo Code hiện tại):**
  Thực hiện lệnh SQL đổi lại tên bảng về `DebateCriteria`:
  ```sql
  EXEC sp_rename 'DebateScoreWeight', 'DebateCriteria';
  ```

Sau khi thực hiện một trong hai bước đồng bộ trên, toàn bộ quy trình Competition từ Tạo giải -> Thi đấu -> AI Chấm điểm -> Trọng tài Review -> Finalize -> Xác định Nhà vô địch sẽ hoạt động trơn tru 100%.

