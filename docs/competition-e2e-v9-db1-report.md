# BÁO CÁO KIỂM THỬ E2E COMPETITION TRÊN DATABASE DebatePracticePlatformDB1
**Dự án:** AI Debate Practice Platform (ADPP)  
**Thời gian thực hiện:** 2026-11-14  
**Người thực hiện:** Senior QA Automation Engineer & System Architect  
**Phạm vi:** Kiểm tra điều kiện tiên quyết, xác minh tính toàn vẹn schema trên `DebatePracticePlatformDB1`, đối soát cấu hình kết nối của Backend, và đánh giá an toàn trước khi thực thi E2E.  

---

## 1. Git Branch và Commit Hash

* **Branch hiện tại:** `competition` (Trùng khớp với branch yêu cầu).
* **Trạng thái Git:** Clean (Chỉ có thay đổi `appsettings.json` trỏ tới `DebatePracticePlatformDB1` do người dùng cập nhật).
* **Commit Hash đang kiểm tra:** `17cd5ab44b478cf5bf4400d65ed9507073ad1cc9`
* **Commit Message:** `Fix bracket in competition`

---

## 2. Database Thực tế và Rủi ro Môi trường Phát hiện Được

Theo Quy tắc An toàn Tuyệt đối (**Critical Database Safety Rules**):
> *"Database được phép sử dụng duy nhất: `DebatePracticePlatformDB1`."*  
> *"Tuyệt đối không sửa `DebatePracticePlatformDB`. Nếu không thể xác nhận đúng database, phải dừng và báo cáo."*

### Phát hiện Nghiêm trọng (Safety Gate Triggered):
1. **Tiến trình Backend đang chạy (`SystemService.exe`, PID: `13632`):**
   - Đang chạy ngầm trên cổng `http://localhost:5001`.
   - Bị khóa file (File Lock) bởi `Microsoft Visual Studio (PID: 23432)` và `SystemService (PID: 13632)`.
2. **Cấu hình Connection String thực tế mà tiến trình 13632 đang nạp:**
   - Trong file `appsettings.json`, connection string đã được sửa thành `DebatePracticePlatformDB1`.
   - **TUY NHIÊN**, trong môi trường `Development`, .NET Core tự động ưu tiên nạp **User Secrets**:
     - File path: `C:\Users\ACER\AppData\Roaming\Microsoft\UserSecrets\9b0bca70-8b35-498d-a43f-4f1565b5c87d\secrets.json`
     - Nội dung dòng 10:
       ```json
       "DefaultConnection": "Server=localhost\\SQLEXPRESS;Database=DebatePracticePlatformDB;Trusted_Connection=True;TrustServerCertificate=True;"
       ```
     - User Secrets ghi đè cấu hình và trỏ về **`DebatePracticePlatformDB` (Database cũ cần bảo vệ)**!
3. **Bằng chứng thực tế:**
   - Gọi API thăm dò: `GET http://localhost:5001/api/competitions`
   - Dữ liệu trả về: `[{"competitionId": 41, "title": "ADPP Test Individual 1v1", ...}]`
   - Kiểm tra trực tiếp qua SQL Server:
     - `SELECT COUNT(*) FROM Competitions` trên `DebatePracticePlatformDB1`: **0 dòng (rỗng)**.
     - `SELECT COUNT(*) FROM Competitions` trên `DebatePracticePlatformDB`: **1 dòng (chính là CompetitionId 41)**.
   - 👉 **KẾT LUẬN:** Nếu kích hoạt chạy bộ test E2E vào `http://localhost:5001` lúc này, toàn bộ dữ liệu sẽ ghi trực tiếp vào `DebatePracticePlatformDB` (vi phạm nghiêm trọng nguyên tắc an toàn).

---

## 3. Xác nhận Schema Verification trên `DebatePracticePlatformDB1`

Đã thực hiện các câu lệnh T-SQL READ-ONLY trực tiếp tới cơ sở dữ liệu `DebatePracticePlatformDB1` trên instance `THANH-SANGG\SQLEXPRESS`:

| Hạng mục kiểm tra | Lệnh T-SQL xác minh | Kết quả thực tế | Đánh giá |
| :--- | :--- | :--- | :--- |
| **Instance & DB Name** | `SELECT @@SERVERNAME, DB_NAME()` | `DESKTOP-DI46HNF\SQLEXPRESS`, `DebatePracticePlatformDB1` | **ĐÚNG DATABASE** |
| **Cột Difficulty** | `SELECT COL_LENGTH('DebateSessions', 'Difficulty')` | **`NULL`** | **THIẾU CỘT (MISMATCH)** |
| **Các cột của DebateSessions** | `INFORMATION_SCHEMA.COLUMNS` | 9 cột: `DebateSessionId`, `TopicId`, `FormatId`, `CreatedBy`, `Status`, `StartTime`, `EndTime`, `CreatedAt`, `UpdatedAt` | **KHÔNG CÓ CỘT `Difficulty`** |
| **Bảng DebateCriteria** | `SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME IN ('DebateCriteria', 'DebateScoreWeight')` | **`DebateScoreWeight`** | **LỆCH TÊN BẢNG (BREAKING)** |
| **EF Migrations History** | `OBJECT_ID('__EFMigrationsHistory')` | **`TABLE_DOES_NOT_EXIST`** | Chưa chạy EF Migration |

### Nguyên nhân Schema Mismatch trên `DebatePracticePlatformDB1`:
- Trong file `DatabaseSEP/AIDebate-V0.9.sql`, tại dòng 2191 có lệnh `USE DebatePracticePlatformDB; GO`.
- Do đó, khi người dùng thực thi script V9 để dựng `DebatePracticePlatformDB1`, lệnh dòng 2205 (`ALTER TABLE [DebateSessions] ADD [Difficulty] nvarchar(50) NULL;`) đã bị chuyển ngữ cảnh sang DB cũ hoặc bị bỏ sót, khiến `DebatePracticePlatformDB1` **vẫn chưa có cột `Difficulty`**.
- Đồng thời, lệnh dòng 2167 (`EXEC sp_rename 'dbo.DebateCriteria', 'DebateScoreWeight'`) đã chạy, khiến bảng bị đổi tên thành `DebateScoreWeight`, trong khi C# Backend (`DebateCriteriaConfiguration.cs#L11`) vẫn đang map vào `DebateCriteria`.

---

## 4. Kết quả Build và Khởi động Backend

* **Build Backend (`dotnet build SystemService.csproj`):**
  - **Trạng thái:** **FAIL (BLOCKED BY FILE LOCK)**
  - **Lỗi:** `MSB3027 / MSB3021: Unable to copy file ... SystemService.DAL.dll / SystemService.BLL.dll. The process cannot access the file because it is being used by another process. The file is locked by: Microsoft Visual Studio (23432), SystemService (13632).`
* **Khởi động Backend:**
  - Backend đang chạy sẵn từ trước tại PID `13632`.
  - Không thể restart tiến trình này nếu không có quyền can thiệp vào tiến trình của Visual Studio, và tiến trình hiện tại đang nhận cấu hình `DebatePracticePlatformDB` từ User Secrets.

---

## 5. Kết quả Kiểm thử E2E: Workflow INDIVIDUAL (1v1)

Do cơ sở dữ liệu `DebatePracticePlatformDB1` thiếu cột `Difficulty` và backend đang chạy kết nối nhầm vào DB cũ, để tuân thủ **Quy tắc An toàn Tuyệt đối** (Dừng và Báo cáo ngay khi phát hiện rủi ro ảnh hưởng DB cũ và Schema Mismatch), các bước test được đánh giá chi tiết:

| Bước | Tên kịch bản | Trạng thái | Ghi chú & Bằng chứng kỹ thuật |
| :--- | :--- | :--- | :--- |
| IND-01 | BTC tạo giải 1v1 | **BLOCKED** | Bị chặn do Kestrel Web API đang trỏ vào DB cũ (`DebatePracticePlatformDB`). |
| IND-02 | Cập nhật & Publish | **BLOCKED** | Không thực hiện để tránh ghi dữ liệu vào DB cũ. |
| IND-03 | User đăng ký (4 entrants) | **BLOCKED** | Không thực hiện. |
| IND-04 | BTC approve registrations | **BLOCKED** | Không thực hiện. |
| IND-05 | Đóng đăng ký | **BLOCKED** | Không thực hiện. |
| IND-06 | Sinh bảng đấu Single Elimination | **BLOCKED** | Cần `DebateSessions` có cột `Difficulty` để EF Core map DTO. |
| IND-07 | Kiểm tra 4 entrants, 2 SF, 1 Final | **BLOCKED** | Bị chặn từ bước IND-06. |
| IND-08 | Start Competition | **BLOCKED** | Bị chặn. |
| IND-09 | **Prepare Debate** | **BLOCKED** | **VẪN BỊ CHẶN BỞI LỖI SCHEMA GỐC:** Trên `DebatePracticePlatformDB1`, `COL_LENGTH('DebateSessions', 'Difficulty')` là `NULL`. EF Core sẽ ném `Invalid column name 'Difficulty'` tại `CompetitionDebateBridgeService.cs#L242`. |
| IND-10 | Start DebateSession | **BLOCKED** | Bị chặn do bước IND-09 không tạo được session. |
| IND-11 | Human vs Human Debate Turns | **BLOCKED** | Bị chặn. |
| IND-12 | AI Evaluation | **BLOCKED** | Bị chặn. |
| IND-13 | BTC Review (`/matches/{id}/review`) | **BLOCKED** | Bị chặn kép: `DebateCriteria` trên DB1 đã bị đổi tên thành `DebateScoreWeight`, EF Core sẽ ném `Invalid object name 'DebateCriteria'`. |
| IND-14 | BTC Finalize Match Winner | **BLOCKED** | Bị chặn do bước IND-13. |
| IND-15 | Winner Propagation sang Final | **BLOCKED** | Bị chặn. |
| IND-16 | Hoàn tất giải đấu (Complete) | **BLOCKED** | Bị chặn. |

---

## 6. Kết quả Kiểm thử E2E: Workflow TEAM (2v2)

| Bước | Tên kịch bản | Trạng thái | Ghi chú & Bằng chứng kỹ thuật |
| :--- | :--- | :--- | :--- |
| TM-01 | BTC tạo giải 2v2 | **BLOCKED** | Bị chặn do an toàn DB. |
| TM-02 | Tạo 4 teams, 8 members | **BLOCKED** | Bị chặn do an toàn DB. |
| TM-03 | Invites & Join Requests | **BLOCKED** | Bị chặn. |
| TM-04 | Team Registration & Approval | **BLOCKED** | Bị chặn. |
| TM-05 | Đóng đăng ký & Sinh Bracket | **BLOCKED** | Bị chặn. |
| TM-06 | Start Competition | **BLOCKED** | Bị chặn. |
| TM-07 | **Prepare Debate (2v2 Mapping)** | **BLOCKED** | **BỊ CHẶN BỞI LỖI SCHEMA:** Cột `Difficulty` chưa có trên `DebateSessions` của `DebatePracticePlatformDB1`. |
| TM-08 | Start DebateSession (4 Debaters) | **BLOCKED** | Bị chặn. |
| TM-09 | Human vs Human Debate Turns | **BLOCKED** | Bị chặn. |
| TM-10 | AI Evaluation | **BLOCKED** | Bị chặn. |
| TM-11 | BTC Review & Finalize Team Winner | **BLOCKED** | Bị chặn bởi lỗi đổi tên bảng `DebateScoreWeight`. |
| TM-12 | WinnerTeamId Propagation & Final | **BLOCKED** | Bị chặn. |

---

## 7. Kết quả Security & Edge Cases

| Kịch bản kiểm tra | Trạng thái | Ghi chú |
| :--- | :--- | :--- |
| SEC-01: BTC-only Authorization | **NOT TESTED** | Chưa thể kiểm thử do môi trường chưa cô lập an toàn. |
| SEC-02: BTC khác không quản lý được giải | **NOT TESTED** | Chưa thể kiểm thử. |
| SEC-03: Participant không thể Finalize | **NOT TESTED** | Chưa thể kiểm thử. |
| SEC-04: Không finalize khi AI chưa xong | **NOT TESTED** | Chưa thể kiểm thử. |
| SEC-05: Chặn duplicate DebateSession khi Prepare | **NOT TESTED** | Chưa thể kiểm thử. |
| SEC-06: Chặn sinh bracket hai lần | **NOT TESTED** | Đã được code guard tại `CompetitionTournamentService.cs`. |

---

## 8. Bảng So sánh Tổng hợp giữa E2E Lần trước và Lần này

| Chỉ số / Hạng mục | Lần E2E trước (13/11) | Lần này (14/11) | Diễn biến thực tế |
| :--- | :--- | :--- | :--- |
| **Database mục tiêu** | `DebatePracticePlatformDB` | `DebatePracticePlatformDB1` | Mục đích đổi DB để cô lập rủi ro. |
| **Cột Difficulty** | Chưa có (`NULL`) | **Vẫn chưa có (`NULL`)** | File V9 chưa apply thành công lệnh ADD COLUMN vào DB1. |
| **Bảng DebateCriteria** | `DebateCriteria` (Hợp lệ) | `DebateScoreWeight` (**Lệch EF**) | File V9 chạy lệnh rename gây hỏng mapping Backend. |
| **Kết nối Backend thực tế** | Kết nối `DebatePracticePlatformDB` | **Vẫn kết nối `DebatePracticePlatformDB`** | User Secrets ghi đè `appsettings.json`. |
| **Tiến độ Workflow** | Chạy tới bước Start Competition | **DỪNG NGAY Ở PRE-CHECK (SAFETY STOP)** | Phát hiện rủi ro tác động DB cũ và schema DB1 lỗi. |

---

## 9. Kết luận về `Prepare Debate` và Hành động Cần thiết

### 1. `Prepare Debate` đã hoạt động hay chưa?
👉 **CHƯA HOẠT ĐỘNG TRÊN DATABASE MỚI.**  
`DebatePracticePlatformDB1` vẫn đang thiếu cột `Difficulty` trên bảng `DebateSessions`, do đó nếu gọi Prepare Debate thì EF Core vẫn sẽ gặp đúng lỗi `Invalid column name 'Difficulty'`. Đồng thời, việc đổi tên `DebateCriteria` thành `DebateScoreWeight` trên DB1 tạo thêm một lỗi gãy thứ hai (Breaking Bug) ở bước Review & Finalize.

### 2. Hai việc CẦN LÀM trước khi có thể chạy lại E2E thật sự:
1. **Cập nhật User Secrets của Backend:**
   Chạy lệnh hoặc sửa file `secrets.json` để trỏ DefaultConnection sang `DebatePracticePlatformDB1`:
   ```bash
   dotnet user-secrets set "ConnectionStrings:DefaultConnection" "Server=THANH-SANGG\SQLEXPRESS;Database=DebatePracticePlatformDB1;Trusted_Connection=True;TrustServerCertificate=True;" --project Services/SystemService/SystemService.csproj
   ```
   Sau đó tắt tiến trình 13632 và chạy lại Backend để nhận cấu hình mới.
2. **Sửa Schema trên `DebatePracticePlatformDB1`:**
   Chạy 2 câu lệnh SQL để chuẩn hóa DB1:
   ```sql
   USE DebatePracticePlatformDB1;
   GO
   -- 1. Bổ sung cột Difficulty
   IF COL_LENGTH('DebateSessions', 'Difficulty') IS NULL
       ALTER TABLE [DebateSessions] ADD [Difficulty] nvarchar(50) NULL;

   -- 2. Đổi lại tên bảng DebateCriteria để khớp với C# Entity
   IF OBJECT_ID('dbo.DebateScoreWeight') IS NOT NULL AND OBJECT_ID('dbo.DebateCriteria') IS NULL
       EXEC sp_rename 'dbo.DebateScoreWeight', 'DebateCriteria', 'OBJECT';
   GO
   ```

