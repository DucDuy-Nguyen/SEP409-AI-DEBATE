# SystemService

ASP.NET Core 8 API của ADPP: tài khoản, phiên tranh biện, giải đấu, thanh toán. Tài liệu này chỉ mô tả phần **chấm điểm phiên
tranh biện** (AI Evaluator) và những điều cần biết khi chạy / deploy phần đó.

## Chấm điểm phiên tranh biện

Kết quả chính thức của một phiên là bản ghi `AIJudgement` (cột `RawResponseJson` giữ toàn bộ kết quả từng vòng, gồm kiểm
chứng số liệu). FE đọc nó qua `GET /api/debate/{id}/evaluation`.

1. **Nộp lượt cuối** (`POST /api/debate/{id}/arguments`, `.../ai-arguments`, lượt cuối của phòng 2v2): ghi lượt, đóng phiên
   (trận đấu giải liên kết chuyển sang `Evaluating`), commit, rồi **bắt đầu chấm ở nền** và trả phản hồi ngay.
2. **Chấm** (`DebateService.EvaluateAndStoreSessionInternalAsync`): gọi AI Evaluator `/evaluate/round` cho mỗi vòng × mỗi phe
   song song (phe AI gửi `check_evidence=false`; `topic` lấy từ `Topic.Category` nếu thuộc education / environment /
   technology / society), rồi `/evaluate/session` cho 2 phe song song, có `skipped_stages` (vòng không phát biểu tính 0 điểm).
3. **`GET /api/debate/{id}/evaluation`**: có judgement thì trả luôn; phiên đang được chấm thì chờ đúng lần chấm đó; phiên đã
   xong mà chưa có judgement (lần chấm nền lỗi) thì chấm lại. `POST /api/debate/{id}/evaluate` dùng chung cơ chế.
4. Trả về FE: DTO camelCase, `evidenceChecks` mỗi vòng **không có** field `error` (lỗi kỹ thuật chỉ nằm trong
   `RawResponseJson` và log).

### Một replica (quan trọng khi deploy)

`DebateEvaluationCoordinator` (singleton) bảo đảm mỗi phiên chỉ được chấm một lần **trong một process**: các yêu cầu đến
cùng lúc chờ chung một Task, và lần chấm chạy trong DI scope riêng (không dùng DbContext của request đã kích hoạt nó).
Khóa này nằm trong bộ nhớ, nên:

- **SystemService phải chạy 1 replica.** Với 2 replica trở lên, mỗi replica có thể chấm cùng một phiên (2 lần gọi AI,
  2 `AIJudgement`).
- Muốn scale ra nhiều replica thì phải chuyển khóa xuống DB (ví dụ unique index trên `AIJudgements.DebateSessionId` hoặc
  bảng khóa), cần migration.
- Lúc khởi động service ghi 1 dòng log: `DebateEvaluationCoordinator is in-memory: run SystemService as a single replica ...`.
- Repo hiện không có cấu hình Azure Container Apps cho SystemService: cần kiểm tra `min/max replicas` trên Azure
  (nên đặt `maxReplicas = 1`).
- Nếu process dừng giữa lúc chấm nền, lần `GET /evaluation` sau sẽ chấm lại.

### Khởi động sẵn (warm-up)

`HostedServices/StartupWarmupService` chạy nền ngay sau khi khởi động (không chặn startup, lỗi chỉ ghi warning): chạy query EF
giống query của lần chấm, và gọi `GET {AiServices:EvaluatorUrl}/health/ready`. Đo được: lần chấm đầu sau khởi động 34 s khi
không có warm-up, 23,3 s khi có.

### Timeout

| Tầng | Giá trị | Ở đâu |
|---|---|---|
| SystemService → AI Evaluator | 120 s mỗi lần gọi | `AiServices:TimeoutSeconds` |
| Gateway (YARP) → SystemService | 180 s | `Gateway/appsettings.json`, `system-cluster` |
| FE → `GET /evaluation` | 200 s | FE `debateApi.getEvaluation` |

Đo trên máy local: p95 từ lúc nộp lượt cuối đến lúc có báo cáo là 20,2 s (5 phiên); chi tiết ở
`AiServices/ai-evaluator-service/docs/RAG_REPORT_DEMO_RESULTS.md`.

## Chạy local với AI Evaluator local

Không cần sửa `appsettings.json`; ghi đè bằng biến môi trường (PowerShell):

```powershell
$env:AiServices__EvaluatorUrl = "http://localhost:8000"
$env:ConnectionStrings__DefaultConnection = "Server=localhost;Database=<db>;Trusted_Connection=True;TrustServerCertificate=True"
dotnet run --project Services/SystemService --urls http://localhost:5001
```

Kiểm chứng số liệu chỉ chạy khi AI Evaluator bật `RAG_ENABLED=true` và phiên có chủ đề với `Category` thuộc 4 chủ đề trên
(phòng AI, 1v1, 2v2 đều nhận `topicId` để lấy đúng chủ đề).

## Chạy demo RAG local

DB dùng cho demo D1–D6 (`AiServices/ai-evaluator-service/docs/RAG_REPORT_DEMO_RESULTS.md`):
**`DebatePracticePlatformDB_RagDemo`** trên SQL Server local (Windows auth). DB này riêng cho demo, không đụng DB của nhóm.

**Vì sao không dùng migration:** các migration trong `SystemService.DAL/Migrations` đã cũ so với model (thiếu `Topics`,
`DebateRounds`, `AIJudgements`, ...), nên DB demo được dựng thẳng từ model EF hiện tại.

1. Tạo schema từ model (không thêm migration):

   ```powershell
   $env:ConnectionStrings__DefaultConnection = "Server=localhost;Database=DebatePracticePlatformDB_RagDemo;Trusted_Connection=True;TrustServerCertificate=True"
   dotnet ef dbcontext script --project Services/SystemService.DAL --startup-project Services/SystemService --output schema.sql
   sqlcmd -S localhost -E -Q "CREATE DATABASE DebatePracticePlatformDB_RagDemo"
   sqlcmd -S localhost -E -I -d DebatePracticePlatformDB_RagDemo -i schema.sql   # -I: bật QUOTED_IDENTIFIER cho filtered index
   ```

2. Seed tối thiểu (SQL). `<BCRYPT_HASH>` là hash BCrypt của mật khẩu demo (BCrypt.Net-Next, giống `AuthService`);
   tài khoản `.local` đã đánh dấu xác minh email nên không cần OTP và không bao giờ nhận mail:

   ```sql
   INSERT INTO Roles (RoleName, Description, CreatedAt) VALUES (N'Member', N'Học viên', SYSUTCDATETIME());
   SET IDENTITY_INSERT DebateFormats ON;
   INSERT INTO DebateFormats (FormatId, FormatName, MaxParticipants, TotalRounds, RoundDurationSeconds, IsActive, CreatedAt)
   VALUES (1, N'User vs AI', 2, 3, 180, 1, SYSUTCDATETIME()), (2, N'1 vs 1', 2, 3, 180, 1, SYSUTCDATETIME());
   SET IDENTITY_INSERT DebateFormats OFF;
   INSERT INTO Users (FullName, Email, PasswordHash, IsEmailVerified, IsActive, CreatedAt) VALUES
     (N'Debater A (RAG demo)', N'debater.a@ragdemo.local', N'<BCRYPT_HASH>', 1, 1, SYSUTCDATETIME()),
     (N'Debater B (RAG demo)', N'debater.b@ragdemo.local', N'<BCRYPT_HASH>', 1, 1, SYSUTCDATETIME());
   INSERT INTO UserRoles (UserId, RoleId, AssignedAt) SELECT u.UserId, r.RoleId, SYSUTCDATETIME() FROM Users u CROSS JOIN Roles r;
   INSERT INTO Topics (Title, Description, Category, Difficulty, IsActive, CreatedAt) VALUES
     (N'Học thông qua chơi ở tiểu học', N'Phương pháp học thông qua chơi nên được áp dụng rộng rãi ở bậc tiểu học', N'Education', N'Medium', 1, SYSUTCDATETIME()),
     (N'Mạng xã hội và giới trẻ', N'Mạng xã hội gây hại nhiều hơn lợi cho giới trẻ', N'Society', N'Medium', 1, SYSUTCDATETIME());
   ```

3. Chạy: AI Evaluator local với `RAG_ENABLED=true` (cổng 8000, kho fact pgvector đang chạy), SystemService với
   `AiServices__EvaluatorUrl=http://localhost:8000` và connection string ở bước 1, FE `npm run dev` (cổng 5173, proxy `/api`
   sang 5001). Chủ đề Education có kho fact; Society chưa có (panel báo "chưa có kho dữ kiện").
