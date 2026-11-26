# Secrets & cấu hình

Repo này **public**. Không commit giá trị thật nào: khóa, token, mật khẩu, connection string có mật khẩu, URL DB server.
File cấu hình trong repo chỉ giữ cấu trúc, các giá trị nhạy cảm để `""`.

## Đặt giá trị thật ở đâu

| Nơi chạy | SystemService (.NET) | AI services (Python) / FE |
|---|---|---|
| Máy dev | `dotnet user-secrets` (lưu ở `%APPDATA%\Microsoft\UserSecrets`, ngoài repo) | file `.env` (đã git-ignore) trong thư mục service: copy từ `.env.example` / `.env.prod.example` nếu có, không thì xem tên biến trong `app/config.py` (`app/core/config.py`) của service; FE: `.env.example` của repo FE |
| `run-all.ps1 -Azure` | `.azure-db.env` (đã git-ignore), copy từ `.azure-db.env.example` | như trái |
| Azure / Docker | biến môi trường của Container App / VM (hoặc Key Vault) | biến môi trường |

Ví dụ user-secrets (chạy ở thư mục gốc repo):

```powershell
dotnet user-secrets set "Jwt:Key" "<chuỗi ngẫu nhiên ≥ 32 ký tự>" --project Services/SystemService
dotnet user-secrets set "ConnectionStrings:DefaultConnection" "Server=localhost\MYINSTANCE;Database=DebatePracticePlatformDB;Trusted_Connection=True;TrustServerCertificate=True" --project Services/SystemService
dotnet user-secrets list --project Services/SystemService
```

Tạo khóa ngẫu nhiên: `[Convert]::ToBase64String((1..48 | % { Get-Random -Max 256 }) -as [byte[]])` (PowerShell)
hoặc `openssl rand -base64 48`.

### Biến của SystemService

Tên biến môi trường = khóa cấu hình, `:` thay bằng `__`.

| Khóa | Bắt buộc ngoài Development | Ghi chú |
|---|---|---|
| `Jwt:Key` (`Jwt__Key`) | **có**, ≥ 32 byte, không phải khóa dev | thiếu thì service không khởi động. Development dùng khóa dev công khai |
| `ConnectionStrings:DefaultConnection` | **có** | Development mặc định `Server=localhost;Database=DebatePracticePlatformDB;Trusted_Connection=True` |
| `AiServices:EvaluatorUrl`, `AiServices:OpponentUrl` | không | trống = mặc định trong `Program.cs` |
| `PayOS:*`, `EmailSettings:Username/Password`, `GoogleAuth:ClientId` | theo tính năng | |
| `TeamCall:Cloudflare:TurnKeyId/TurnKeyApiToken` | không | trống = chỉ STUN |

## Chặn secret trước khi push

1. **Hook pre-commit** (bật 1 lần cho mỗi clone):
   ```bash
   git config core.hooksPath .githooks
   ```
   Hook chạy [gitleaks](https://github.com/gitleaks/gitleaks) trên các thay đổi đã `git add`. Cài bằng
   `winget install gitleaks`, hoặc để Docker Desktop chạy là đủ (hook dùng image `zricethezav/gitleaks`).
   Không có cả hai thì hook chỉ cảnh báo, không chặn.
2. **CI** `.github/workflows/secret-scan.yml`: quét các commit mới của mọi push / PR, kể cả khi ai đó chưa bật hook
   hoặc dùng `--no-verify`.
3. **GitHub Push Protection** (chủ repo bật): *Settings → Code security → Secret scanning → Push protection*.
   GitHub từ chối push chứa khóa của các nhà cung cấp đã biết.

Quy tắc ở `.gitleaks.toml` (bộ mặc định + connection string SQL Server / URL Postgres có mật khẩu).
Báo nhầm: thêm **đúng** giá trị hoặc đường dẫn đó vào allowlist trong một PR có review, không thêm pattern rộng.

## Lỡ commit một secret

1. **Coi như đã lộ**: đổi / thu hồi ngay khóa đó ở nơi cấp (Azure, Cloudflare, Google, PayOS...). Xóa khỏi file rồi
   commit lại **không** đủ, vì giá trị vẫn nằm trong lịch sử git và trên các bản clone.
2. Chuyển giá trị sang user-secrets / `.env` / biến môi trường như trên.
3. Chỉ viết lại lịch sử (git filter-repo) khi cả nhóm thống nhất. Sau khi đã đổi khóa thì thường không cần.

Các secret đã nằm trong lịch sử được liệt kê (fingerprint, không có giá trị) ở `.gitleaksignore` để quét toàn bộ
lịch sử vẫn dùng được. **Mỗi dòng ở đó là một giá trị phải đổi**: mật khẩu SMTP (`EmailSettings:Password`,
commit 27/09 → 12/10/2026) và `Jwt:Key` của IdentityService cũ. Không bao giờ thêm phát hiện mới vào file này.

Lịch sử repo còn khóa JWT dev cũ (`appsettings.json` trước commit `da8fd6c`). Môi trường thật phải dùng một
`Jwt__Key` riêng, `Program.cs` từ chối khởi động với khóa dev.
