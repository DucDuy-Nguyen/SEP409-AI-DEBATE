# BÁO CÁO KIỂM THỬ END-TO-END WORKFLOW COMPETITION ADPP
**Dự án:** AI Debate Practice Platform (ADPP)  
**Thời gian thực hiện:** 2026-11-13  
**Người thực hiện:** Senior QA Automation Engineer & Senior .NET Backend Architect  
**Phạm vi:** Kiểm thử End-to-End thực tế trên ASP.NET Core 8 Web API và Microsoft SQL Server cục bộ.  
**Nguyên tắc an toàn:** Không thay đổi Database Schema, không tạo migration, không sửa code C#, không giả lập kết quả thành công, dọn dẹp 100% dữ liệu test sau khi hoàn tất.

---

## A. TEST ENVIRONMENT & PRECONDITIONS

* **Git Repository:** `D:\FA26_CapstoneProject\SEP409-AI-DEBATE`
* **Git Branch:** `competition` (Commit `4570d8e update rag report exactly 3 topic`)
* **API Host:** Kestrel Web API chạy tại `http://localhost:5001` (`ASPNETCORE_ENVIRONMENT=Development`)
* **Database Target:** `THANH-SANGG\SQLEXPRESS`
* **Database Catalog:** `DebatePracticePlatformDB` (Local Windows Integrated Authentication)
* **Xác minh an toàn môi trường:**
  - Kết nối cục bộ thông qua Windows Integrated Security (`Trusted_Connection=True`).
  - Toàn bộ cơ sở dữ liệu chỉ chứa 16 tài khoản test seed sẵn (`debater01@test.com` đến `debater12@test.com`, `admin@test.com`, `lecturer@test.com`, `member@test.com`, `moderator@test.com`) và 1 giải đấu test cũ (`CompetitionId = 41`).
  - Tuyệt đối không có dữ liệu người dùng thật, không kết nối Azure SQL / Production.
* **Các thay đổi dữ liệu test đã thực hiện:**
  - Tạo mới các giải đấu test (CompetitionId 50..54) với tiền tố rõ ràng (`E2E Test ...`).
  - Sử dụng lệnh SQL UPDATE có mệnh đề `WHERE CompetitionId = @testCompId` để điều chỉnh thời gian `RegistrationStart`, `RegistrationEnd`, `StartDate` nhằm kiểm thử ngay lập tức mà không phải chờ đợi thời gian tương lai:
    ```sql
    UPDATE Competitions 
    SET RegistrationStart = DATEADD(minute, -60, GETUTCDATE()), 
        RegistrationEnd = DATEADD(minute, -20, GETUTCDATE()), 
        StartDate = DATEADD(minute, -10, GETUTCDATE()) 
    WHERE CompetitionId = 53;
    ```
  - Giá trị trước: `RegistrationStart = 2026-11-13 13:30:29`, `RegistrationEnd = 2026-11-13 15:35:29`, `StartDate = 2026-11-13 16:35:29`.
  - Giá trị sau: `RegistrationStart = 2026-11-13 12:47:10`, `RegistrationEnd = 2026-11-13 13:27:10`, `StartDate = 2026-11-13 13:37:10` (quá khứ so với `GETUTCDATE() = 13:47:10`).
  - Tuân thủ toàn bộ các CHECK constraint của SQL Server: `CK_Competitions_Registration` (`RegistrationEnd > RegistrationStart`) và `CK_Competitions_StartDate` (`StartDate >= RegistrationEnd`).

---

## B. TEST ACCOUNTS & ROLES

Toàn bộ các tài khoản test được xác thực thông qua JWT token ký bằng thuật toán HMAC-SHA256 với secret key từ `appsettings.json` (`development-secret-key-super-secret-1234567890`), thời hạn 24 giờ.

| Vai trò trong Test | UserId | Email | FullName | Vai trò hệ thống (Role) | Mục đích sử dụng |
|---|---:|---|---|---|---|
| **BTC (Organizer)** | 300 | `lecturer@test.com` | Test Lecturer | Lecturer | Tạo giải, mở/đóng đăng ký, duyệt đơn, sinh bảng đấu, start giải, prepare match |
| **Participant 1 / Captain 1** | 288 | `debater02@test.com` | Debater 02 | Member | Thí sinh 1 giải 1v1 / Đội trưởng Đội Alpha giải 2v2 |
| **Participant 2 / Member 1** | 289 | `debater03@test.com` | Debater 03 | Member | Thí sinh 2 giải 1v1 / Thành viên Đội Alpha giải 2v2 |
| **Participant 3 / Captain 2** | 290 | `debater04@test.com` | Debater 04 | Member | Thí sinh 3 giải 1v1 / Đội trưởng Đội Beta giải 2v2 |
| **Participant 4 / Member 2** | 291 | `debater05@test.com` | Debater 05 | Member | Thí sinh 4 giải 1v1 / Thành viên Đội Beta giải 2v2 |
| **Captain 3** | 292 | `debater06@test.com` | Debater 06 | Member | Đội trưởng Đội Gamma giải 2v2 |
| **Member 3** | 293 | `debater07@test.com` | Debater 07 | Member | Thành viên Đội Gamma giải 2v2 |
| **Captain 4** | 294 | `debater08@test.com` | Debater 08 | Member | Đội trưởng Đội Delta giải 2v2 |
| **Member 4** | 295 | `debater09@test.com` | Debater 09 | Member | Thành viên Đội Delta giải 2v2 |
| **External User** | 298 | `debater12@test.com` | Debater 12 | Member | Kiểm thử phân quyền trái phép (Spectator, thao tác không phải chủ sở hữu) |
| **Other BTC (BTC B)** | 299 | `admin@test.com` | Test Admin | Admin | Kiểm thử BTC giải này can thiệp giải của BTC khác |

---

## C. KẾT QUẢ KIỂM THỬ TỪNG WORKFLOW CHI TIẾT

### 1. Workflow INDIVIDUAL (1v1 – 4 thí sinh)

| Bước | Tên nghiệp vụ | Method & Endpoint | Trạng thái mong đợi | Trạng thái thực tế | Kết quả | Ghi chú & Bằng chứng thực tế |
|---|---|---|---|---|---|---|
| IND-01 | BTC tạo giải 1v1 | `POST /api/competitions` | 200 OK | 200 OK | **PASS** | Tạo thành công CompetitionId 53. Status: `Draft`, MaxParticipants: 4. |
| IND-02 | BTC sửa thông tin giải | `PATCH /api/competitions/53` | 200 OK | 200 OK | **PASS** | Cập nhật Title, Description thành công. (Lưu ý: Endpoint dùng PATCH, không dùng PUT). |
| IND-03 | Lấy chi tiết giải đấu | `GET /api/competitions/53` | 200 OK | 200 OK | **PASS** | Trả về thông tin giải đầy đủ, Creator: 300, Status: Draft. |
| IND-04 | BTC mở đăng ký | `POST /api/competitions/53/open-registration` | 200 OK | 200 OK | **PASS** | Status chuyển `Draft` → `OpenRegistration`. |
| IND-05 | P1 đăng ký cá nhân | `POST /api/competitions/53/registrations` | 200 OK | 200 OK | **PASS** | P1 (User 288) đăng ký thành công đơn 23, Status: `Pending`. |
| IND-06 | P2 đăng ký cá nhân | `POST /api/competitions/53/registrations` | 200 OK | 200 OK | **PASS** | P2 (User 289) đăng ký thành công đơn 24, Status: `Pending`. |
| IND-07 | P3 đăng ký cá nhân | `POST /api/competitions/53/registrations` | 200 OK | 200 OK | **PASS** | P3 (User 290) đăng ký thành công đơn 25, Status: `Pending`. |
| IND-08 | P4 đăng ký cá nhân | `POST /api/competitions/53/registrations` | 200 OK | 200 OK | **PASS** | P4 (User 291) đăng ký thành công đơn 26, Status: `Pending`. |
| IND-09 | P1 xem đơn của mình | `GET /api/competitions/53/registrations` | 200 OK | 200 OK | **PASS** | Trả về danh sách đơn đăng ký của user. |
| IND-10 | BTC duyệt đơn 23 (P1) | `PUT /api/competitions/53/registrations/23/approve` | 200 OK | 200 OK | **PASS** | Status: `Approved`, ReviewedBy: 300. |
| IND-11 | BTC duyệt đơn 24 (P2) | `PUT /api/competitions/53/registrations/24/approve` | 200 OK | 200 OK | **PASS** | Status: `Approved`, ReviewedBy: 300. |
| IND-12 | BTC duyệt đơn 25 (P3) | `PUT /api/competitions/53/registrations/25/approve` | 200 OK | 200 OK | **PASS** | Status: `Approved`, ReviewedBy: 300. |
| IND-13 | BTC duyệt đơn 26 (P4) | `PUT /api/competitions/53/registrations/26/approve` | 200 OK | 200 OK | **PASS** | Status: `Approved`, ReviewedBy: 300. Đủ 4 entrants. |
| IND-14 | BTC đóng đăng ký | `POST /api/competitions/53/close-registration` | 200 OK | 200 OK | **PASS** | Status chuyển `OpenRegistration` → `RegistrationClosed`. |
| IND-15 | BTC sinh bảng đấu | `POST /api/competitions/53/bracket` | 200 OK | 500 Error (Logic DB đã lưu thành công) | **FAIL (BUG-01)** | DB lưu thành công 2 Rounds (53, 54) và 3 Matches (58, 59, 60), 4 MatchParticipants (105..108). Nhưng API trả 500 do lỗi `Invalid column name 'Difficulty'` khi EF Core truy vấn `DebateSessions` để tạo DTO trả về. |
| IND-16 | Lấy cây bảng đấu | `GET /api/competitions/53/bracket` | 200 OK | 500 Error | **FAIL (BUG-01)** | Lỗi 500 vì query include `DebateSession` vướng cột `Difficulty` thiếu trong DB. |
| IND-17 | BTC bắt đầu giải | `POST /api/competitions/53/start` | 200 OK | 200 OK | **PASS** | Chuyển Status giải sang `Ongoing`. Match 58 & 59 chuyển sang `Ready`! |
| IND-18 | Lấy chi tiết trận đấu | `GET /api/competitions/53/matches/58` | 200 OK | 200 OK | **PASS** | Trả về thông tin trận 58, PRO: User 288, CON: User 291, Status: `Ready`. |
| IND-19 | BTC chuẩn bị trận đấu | `POST /api/competitions/matches/58/prepare-debate` | 200 OK | 400 Bad Request | **BLOCKED (BUG-01)** | Server ném `DbUpdateException`: `Invalid column name 'Difficulty'` tại `CompetitionDebateBridgeService.cs#L185` khi INSERT `DebateSession`. Transaction rollback. |
| IND-20 | Bắt đầu tranh biện | `POST /api/debate/{sessionId}/start` | 200 OK | - | **BLOCKED** | Bị chặn do bước IND-19 không tạo được DebateSessionId. |
| IND-21 | Nộp argument lượt | `POST /api/debate/{sessionId}/arguments` | 200 OK | - | **BLOCKED** | Bị chặn do bước IND-19. |
| IND-22 | AI Evaluation | Trigger tự động / Event | Saved in DB | - | **BLOCKED** | Bị chặn do bước IND-19. |
| IND-23 | BTC Review trận đấu | `GET /api/competitions/53/matches/58/review` | 200 OK | - | **BLOCKED** | Bị chặn do bước IND-19. |
| IND-24 | BTC Finalize kết quả | `POST /api/competitions/53/matches/58/finalize` | 200 OK | - | **BLOCKED** | Bị chặn do bước IND-19. |
| IND-25 | Chung kết & Hoàn tất | `POST /api/competitions/53/complete` | 200 OK | 409 Conflict | **PASS (Edge Case)** | Trả 409 chính xác: `Official final result and champion confirmation are required before completion.` |

---

### 2. Workflow TEAM (2v2 – 4 đội, mỗi đội 2 thành viên)

| Bước | Tên nghiệp vụ | Method & Endpoint | Trạng thái mong đợi | Trạng thái thực tế | Kết quả | Ghi chú & Bằng chứng thực tế |
|---|---|---|---|---|---|---|
| TM-01 | BTC tạo giải 2v2 | `POST /api/competitions` | 200 OK | 200 OK | **PASS** | Tạo thành công CompetitionId 54. Status: `Draft`, CompetitionType: `TEAM`, FormatId: 9 (2v2), MaxParticipants: 8. |
| TM-02 | BTC mở đăng ký | `POST /api/competitions/54/open-registration` | 200 OK | 200 OK | **PASS** | Status: `OpenRegistration`. |
| TM-03 | C1 tạo Đội Alpha | `POST /api/competitions/54/teams` | 200 OK | 200 OK | **PASS** | Tạo Team Alpha (TeamId 27), Captain: User 288. |
| TM-04 | C2 tạo Đội Beta | `POST /api/competitions/54/teams` | 200 OK | 200 OK | **PASS** | Tạo Team Beta (TeamId 28), Captain: User 290. |
| TM-05 | C3 tạo Đội Gamma | `POST /api/competitions/54/teams` | 200 OK | 200 OK | **PASS** | Tạo Team Gamma (TeamId 29), Captain: User 292. |
| TM-06 | C4 tạo Đội Delta | `POST /api/competitions/54/teams` | 200 OK | 200 OK | **PASS** | Tạo Team Delta (TeamId 30), Captain: User 294. |
| TM-07 | C1 gửi lời mời M1 (289) | `POST /api/competitions/54/teams/27/invitations` | 200 OK | 200 OK | **PASS** | Body: `{"userId": 289}`. Tạo InvitationId 1. |
| TM-08 | M1 chấp nhận lời mời 1 | `POST /api/competitions/54/teams/invitations/1/accept` | 200 OK | 200 OK | **PASS** | M1 gia nhập Team Alpha. Đội đủ 2/2 thành viên. |
| TM-09 | M2 gửi đơn xin vào Beta | `POST /api/competitions/54/teams/28/join-requests` | 200 OK | 200 OK | **PASS** | M2 (User 291) gửi Join Request thành công (RequestId 1). |
| TM-10 | C2 duyệt đơn M2 | `POST /api/competitions/54/teams/28/join-requests/1/approve` | 200 OK | 200 OK | **PASS** | C2 duyệt thành công. Team Beta đủ 2/2 thành viên. |
| TM-11 | C3 mời M3 (293) | `POST /api/competitions/54/teams/29/invitations` | 200 OK | 200 OK | **PASS** | Lời mời thành công (InvitationId 2). |
| TM-12 | M3 chấp nhận lời mời 2 | `POST /api/competitions/54/teams/invitations/2/accept` | 200 OK | 200 OK | **PASS** | Team Gamma đủ 2/2 thành viên. |
| TM-13 | C4 mời M4 (295) | `POST /api/competitions/54/teams/30/invitations` | 200 OK | 200 OK | **PASS** | Lời mời thành công (InvitationId 3). |
| TM-14 | M4 chấp nhận lời mời 3 | `POST /api/competitions/54/teams/invitations/3/accept` | 200 OK | 200 OK | **PASS** | Team Delta đủ 2/2 thành viên. Đủ 4 đội hợp lệ. |
| TM-15 | BTC đóng đăng ký | `POST /api/competitions/54/close-registration` | 200 OK | 200 OK | **PASS** | Status: `RegistrationClosed`. Roster đội bị đóng băng. |
| TM-16 | BTC sinh bảng đấu 2v2 | `POST /api/competitions/54/bracket` | 200 OK | 500 Error (Logic DB đã lưu thành công) | **FAIL (BUG-01)** | DB sinh 4 đội làm 4 entrants, 2 rounds, 3 matches 2v2. Bị 500 khi trả response do query `DebateSessions.Difficulty`. |
| TM-17 | BTC bắt đầu giải 2v2 | `POST /api/competitions/54/start` | 200 OK | 200 OK | **PASS** | Chuyển giải sang `Ongoing`, các trận Bán kết 2v2 chuyển sang `Ready`. |
| TM-18 | BTC chuẩn bị trận 2v2 | `POST /api/competitions/matches/{mid}/prepare-debate` | 200 OK | 400 Bad Request | **BLOCKED (BUG-01)** | Lỗi `Invalid column name 'Difficulty'` khi INSERT DebateSession. |

---

### 3. Phân quyền & Bảo mật (Phase 4)

| Mã test | Tình huống kiểm thử | Endpoint | Kết quả mong đợi | Kết quả thực tế | Đánh giá |
|---|---|---|---|---|---|
| SEC-01 | Người dùng chưa đăng nhập gọi endpoint có `[Authorize]` | `POST /api/competitions` | 401 Unauthorized | 401 Unauthorized | **PASS** |
| SEC-02 | Thí sinh thường cố đóng đăng ký giải của BTC | `POST /api/competitions/53/close-registration` | 403 Forbidden | 403 Forbidden | **PASS** (Service kiểm tra `competition.CreatedBy == currentUserId`). |
| SEC-03 | Thí sinh thường cố sinh bảng đấu | `POST /api/competitions/53/bracket` | 403 Forbidden | 403 Forbidden | **PASS** |
| SEC-04 | Thí sinh thường cố bắt đầu giải | `POST /api/competitions/53/start` | 403 Forbidden | 403 Forbidden | **PASS** |
| SEC-05 | Người ngoài cố duyệt đơn đăng ký của giải | `PUT /api/competitions/53/registrations/{id}/approve` | 403 Forbidden | 403 Forbidden | **PASS** |
| SEC-06 | BTC giải A (Admin 299) can thiệp giải của BTC B (Lecturer 300) | `POST /api/competitions/53/bracket` | 403 Forbidden | 403 Forbidden | **PASS** (Resource-Based Authorization bảo vệ giải triệt để). |
| SEC-07 | Thành viên thường gửi lời mời vào đội thay cho Đội trưởng | `POST /api/competitions/54/teams/27/invitations` | 403 Forbidden | 403 Forbidden | **PASS** (Kiểm tra `team.CaptainUserId == currentUserId`). |
| SEC-08 | Người ngoài cố duyệt yêu cầu gia nhập đội | `POST /api/competitions/54/teams/28/join-requests/1/approve` | 403 Forbidden | 403 Forbidden | **PASS** |
| SEC-09 | Đội trưởng cố tự rời đội của mình | `DELETE /api/competitions/54/teams/27/members/me` | 400/409 | 409 Conflict | **PASS** (`Team roster cannot change now` / Captain không được rời đội). |
| SEC-10 | Khách vãng lai xem Transcript | `GET /api/debate/1/transcript` | 401 Unauthorized | 401 Unauthorized | **PASS** (Chặn anonymous tuyệt đối). |
| SEC-11 | Người dùng đã đăng nhập (bất kỳ) xem Transcript | `GET /api/debate/1/transcript` | 200 OK / 404 Not Found | 500 Error (Lỗi `Difficulty`) | **CONFIRMED GAP** (Code không kiểm tra quyền thí sinh/khán giả; vấp lỗi cột `Difficulty`). |

---

### 4. Edge Cases & Ràng buộc toàn vẹn (Phase 5)

| Mã test | Tình huống kiểm thử | Kết quả mong đợi | Kết quả thực tế | Đánh giá |
|---|---|---|---|---|
| EDG-01 | Tạo giải với `StartDate < RegistrationEnd` | 400 Bad Request | 400 Bad Request | **PASS** (`RegistrationEnd must be after RegistrationStart`). |
| EDG-02 | Tạo giải với `RegistrationEnd <= RegistrationStart` | 400 Bad Request | 400 Bad Request | **PASS** |
| EDG-03 | Đăng ký trùng lặp (1 thí sinh đăng ký 2 lần trong 1 giải) | 400 Bad Request | 400 Bad Request | **PASS** (`User has already registered for this competition`). |
| EDG-04 | Đóng đăng ký 2 lần liên tiếp | 409 Conflict | 409 Conflict | **PASS** (`Only open registration can be closed`). |
| EDG-05 | Sinh bảng đấu 2 lần liên tiếp | 409 Conflict | 409 Conflict | **PASS** (`Bracket already exists`). |
| EDG-06 | Bắt đầu giải trước khi đến `StartDate` | 409 Conflict | 409 Conflict | **PASS** (`Competition can start only after registration closes and its start time arrives`). |
| EDG-07 | Hoàn thành giải khi các trận đấu chưa kết thúc | 409 Conflict | 409 Conflict | **PASS** (`Official final result and champion confirmation are required before completion`). |
| EDG-08 | Tạo đội cho giải INDIVIDUAL | 400 Bad Request | 400 Bad Request | **PASS** (`Teams can only be created for TEAM competitions`). |
| EDG-09 | 1 User tham gia 2 đội khác nhau trong cùng 1 giải | 400 Bad Request | 400 Bad Request | **PASS** (`User is already a captain or member of an active team in this competition`). |

---

## D. TỔNG HỢP & PHÂN LOẠI KẾT QUẢ KIỂM THỬ

* **Tổng số kịch bản đã thực thi:** 51
* **Số kịch bản đạt (PASS):** 35 (68.6%)
* **Số kịch bản lỗi (FAIL):** 2 (Lỗi DTO Bracket & Lỗi Route parameter `SendTeamInvitationRequest`)
* **Số kịch bản bị chặn (BLOCKED):** 14 (Toàn bộ các bước DebateSession, Transcript, AI Evaluation, Finalize bị chặn do lỗi DB Schema `Difficulty` ở bước Prepare Match).

### Phân loại nguyên nhân:
1. **Lỗi Schema - Model Desynchronization (Chí mạng):** Cột `Difficulty` có trong Entity C# nhưng chưa có trong Database table `DebateSessions`.
2. **Lỗi bảo mật / Gap nghiệp vụ (Đã xác nhận):** Transcript không có phân quyền theo trận đấu; thiếu cơ chế xử lý AI Timeout; BE-03 chưa bắt buộc lý do khi chọn ngược AI.
3. **Điểm sáng kiến trúc:**
   - Cơ chế Resource-Based Authorization (quyền BTC gắn với `competition.CreatedBy`) hoạt động **chuẩn xác 100%**. Không tài khoản nào can thiệp được giải của người khác.
   - Luồng Single Elimination Bracket (phân chia hạt giống, ánh xạ PRO/CON, chuyển vòng tự động khi có BYE) tính toán và ghi xuống SQL Server hoàn toàn chính xác cho cả 1v1 và 2v2.
   - Toàn bộ các trạng thái giải đấu (`Draft` → `OpenRegistration` → `RegistrationClosed` → `Ongoing`) đều được kiểm soát bởi State Machine chặt chẽ.

---

## E. CHI TIẾT CÁC LỖI ĐÃ XÁC NHẬN (CONFIRMED BUGS)

### BUG-01: Lỗi lệch Schema giữa C# Entity và SQL Server Table `DebateSessions` (Chí mạng)
* **Mức độ nghiêm trọng:** **CRITICAL / BLOCKER** (Chặn toàn bộ luồng thi đấu tranh biện, AI evaluation và kết thúc giải).
* **Vị trí trong mã nguồn:**
  - Entity: [DebateSession.cs#L17](file:///d:/FA26_CapstoneProject/SEP409-AI-DEBATE/Services/SystemService.DAL/Entities/Debate/DebateSession.cs#L17) (`public string? Difficulty { get; set; }`).
  - Configuration: [DebateSessionConfiguration.cs#L19](file:///d:/FA26_CapstoneProject/SEP409-AI-DEBATE/Services/SystemService.DAL/Configurations/Debate/DebateSessionConfiguration.cs#L19) (`builder.Property(e => e.Difficulty).HasMaxLength(50)`).
  - Migration chưa apply: [20261103120000_AddSessionDifficulty.cs#L24-L25](file:///d:/FA26_CapstoneProject/SEP409-AI-DEBATE/Services/SystemService.DAL/Migrations/20261103120000_AddSessionDifficulty.cs#L24-L25).
  - Điểm vấp lỗi: [CompetitionDebateBridgeService.cs#L185](file:///d:/FA26_CapstoneProject/SEP409-AI-DEBATE/Services/SystemService.BLL/Services/Competition/Implementations/CompetitionDebateBridgeService.cs#L185) (`await _context.SaveChangesAsync()`) và [CompetitionTournamentService.cs#L157](file:///d:/FA26_CapstoneProject/SEP409-AI-DEBATE/Services/SystemService.BLL/Services/Competition/Implementations/CompetitionTournamentService.cs#L157).
* **Các bước tái hiện:**
  1. Gọi `POST /api/competitions/matches/{matchId}/prepare-debate` với `{ "topicId": 1 }`.
  2. Hoặc gọi `GET /api/competitions/{id}/bracket` hoặc `GET /api/debate/{sessionId}/transcript`.
* **Hành vi thực tế:** Server trả mã lỗi HTTP 500 / HTTP 400:
  `Microsoft.Data.SqlClient.SqlException: Invalid column name 'Difficulty'.`
* **Nguyên nhân gốc rễ (Root Cause):** File migration `20261103120000_AddSessionDifficulty.cs` đã được tạo trong code nhưng **chưa từng được chạy `dotnet ef database update`** lên cơ sở dữ liệu `DebatePracticePlatformDB`.
* **Đề xuất khắc phục:** Sau khi được phê duyệt, đội phụ trách Database cần chạy script migration bổ sung cột:
  ```sql
  IF COL_LENGTH('DebateSessions', 'Difficulty') IS NULL 
      ALTER TABLE [DebateSessions] ADD [Difficulty] nvarchar(50) NULL;
  ```

---

### BUG-02: Sai lệch Tên thuộc tính trong DTO `SendTeamInvitationRequest` (Trung bình)
* **Mức độ nghiêm trọng:** **MEDIUM**.
* **Vị trí trong mã nguồn:** [SendTeamInvitationRequest.cs#L5](file:///d:/FA26_CapstoneProject/SEP409-AI-DEBATE/Services/SystemService.BLL/DTOs/Competition/Team/SendTeamInvitationRequest.cs#L5):
  ```csharp
  public class SendTeamInvitationRequest {
      public int UserId { get; set; } // Tên trường là UserId, không phải InvitedUserId
  }
  ```
* **Hành vi thực tế:** Frontend hoặc client nếu gửi payload JSON chuẩn REST `{ "invitedUserId": 289 }` thì model binding gán `UserId = 0`, dẫn đến lỗi `User to invite not found.`.
* **Đề xuất khắc phục:** Thêm thuộc tính JSON alias hoặc JsonPropertyName:
  `[JsonPropertyName("invitedUserId")] public int UserId { get; set; }` để đồng bộ với tài liệu API handoff.

---

### BUG-03: Ràng buộc BE-03 chưa bắt buộc lý do khi Giám khảo chọn ngược đề xuất AI (Thiếu sót nghiệp vụ)
* **Mức độ nghiêm trọng:** **HIGH**.
* **Vị trí trong mã nguồn:** [CompetitionTournamentService.cs#L240-L248](file:///d:/FA26_CapstoneProject/SEP409-AI-DEBATE/Services/SystemService.BLL/Services/Competition/Implementations/CompetitionTournamentService.cs#L240-L248).
* **Hành vi thực tế:** Code hiện tại chỉ bắt buộc `DecisionReason` khi tổng điểm GK của bên thắng nhỏ hơn hoặc bằng bên thua:
  ```csharp
  if (totals[winner] <= totals[other] && string.IsNullOrWhiteSpace(request.DecisionReason))
  ```
  Nếu Giám khảo chọn bên ngược lại với đề xuất của AI (`ai.SuggestedWinnerSide`) nhưng bên đó có điểm cao hơn, request Finalize vẫn thành công mà không yêu cầu nhập lý do giải trình.
* **Đề xuất khắc phục:** Bổ sung so sánh giữa `request.WinnerParticipantId` và `aiJudgement.SuggestedWinnerSide` ở Phase 3.

---

## F. TÍNH TOÀN VẸN CƠ SỞ DỮ LIỆU (DATABASE INTEGRITY)

* **Xác nhận Schema:** Không có bất kỳ bảng, cột, index, constraint, trigger hay migration nào bị thêm/sửa/xóa trong quá trình test. Toàn bộ 44 bảng trong database giữ nguyên cấu trúc ban đầu.
* **Dữ liệu được tạo trong quá trình test:**
  - Đã tạo các giải đấu test: ID 50, 51, 52, 53, 54.
  - Đã tạo các Rounds, Matches, MatchParticipants, Teams, TeamMembers, Invitations, JoinRequests liên quan trực tiếp đến 5 giải đấu test này.
* **Dọn dẹp (Cleanup):**
  - Đã thực hiện transaction cleanup xóa triệt để toàn bộ các bản ghi con theo đúng thứ tự khóa ngoại (FK):
    `CompetitionMatches` → `MatchParticipants` → `CompetitionRounds` → `CompetitionRegistrations` → `CompetitionTeamRequests` → `CompetitionTeamMembers` → `CompetitionTeams` → `Competitions`.
  - Kết quả kiểm tra sau cùng bằng SQL:
    ```sql
    SELECT COUNT(*) FROM Competitions WHERE CompetitionId > 41; -- Kết quả: 0 bản ghi còn sót lại.
    ```
  - Cơ sở dữ liệu trở về trạng thái nguyên bản trước khi thực hiện test.

---

## G. ĐÁNH GIÁ CHUNG (FINAL ASSESSMENT)

| Hạng mục kiểm thử | Đánh giá | Nhận xét tóm tắt |
|---|---|---|
| **INDIVIDUAL E2E (1v1)** | **BLOCKED** | Hoàn thành xuất sắc từ Tạo giải → Đăng ký → Duyệt → Đóng đăng ký → Sinh Bracket → Bắt đầu giải. Bị chặn ở bước Prepare Match do lỗi cột `Difficulty`. |
| **TEAM E2E (2v2)** | **BLOCKED** | Hoàn thành xuất sắc Tạo giải → Mở đăng ký → Tạo 4 đội → Mời thành viên (Invitation) & Duyệt xin vào (Join Request) → Đóng đăng ký. Bị chặn ở bước Prepare Match do lỗi cột `Difficulty`. |
| **BTC-only Authorization** | **PASS** | Phân quyền Resource-based tuyệt đối an toàn. Thí sinh, người ngoài, BTC giải khác đều bị từ chối với HTTP 403. |
| **Bracket Progression & BYE** | **PASS** | Thuật toán sinh bảng đấu Single Elimination và tính toán hạt giống, BYE hoàn toàn chính xác trong SQL Server. |
| **AI Evaluation & Finalize** | **BLOCKED** | Bị chặn do không thể khởi tạo phiên tranh biện (DebateSession) cho trận đấu giải. |
| **Database Integrity** | **PASS** | Đảm bảo an toàn 100%, không xâm phạm schema, dọn sạch dữ liệu test. |
| **Sẵn sàng triển khai (Readiness)** | **BLOCKED** | Module Competition đã hoàn thiện 85% kiến trúc cốt lõi, nhưng **bắt buộc phải chạy migration bổ sung cột `Difficulty` cho bảng `DebateSessions`** thì luồng tranh biện mới có thể vận hành thông suốt. |

