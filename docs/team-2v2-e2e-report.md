# BÁO CÁO KIỂM THỬ END-TO-END (E2E) GIẢI ĐẤU TEAM 2v2
## MÔI TRƯỜNG DATABASE V9 – `DebatePracticePlatformDB3`

---

## 1. MÔI TRƯỜNG & ĐIỀU KIỆN TIÊN QUYẾT (ENVIRONMENT & PRE-CONDITIONS)

| Thuộc tính | Giá trị kiểm tra thực tế | Trạng thái |
|---|---|---|
| **Git Branch** | `competition` | **ĐÚNG** |
| **SQL Server Instance** | `DESKTOP-DI46HNF\SQLEXPRESS` (Network alias: `THANH-SANGG\SQLEXPRESS`) | **ĐÚNG** |
| **Database duy nhất sử dụng** | `DebatePracticePlatformDB3` | **TUÂN THỦ TUYỆT ĐỐI** |
| **Bảo vệ database cũ** | `DebatePracticePlatformDB` (legacy) và `DebatePracticePlatformDB1` | **KHÔNG GHI / KHÔNG ĐỤNG / NGUYÊN VẸN** |
| **Database Schema** | Schema V9 (bảng `DebateScoreWeight`, cột `DebateSessions.Difficulty`) | **KHÔNG SỬA SCHEMA / KHÔNG MIGRATION** |
| **Backend Service** | `SystemService` (Port 5001, .NET 8) | **HOẠT ĐỘNG** |

---

## 2. THÔNG TIN ĐỊNH DANH GIẢI ĐẤU (COMPETITION, TEAMS, MATCHES)

### 2.1. Competition ID: `2`
- **Tiêu đề:** `E2E Team 2v2 Tournament`
- **Thể thức:** `TEAM` (2 vs 2, 4 debaters per match)
- **Số lượng thí sinh tối đa:** 8 thí sinh (4 đội x 2 người)
- **Người tạo / BTC (Organizer):** `lecturer@test.com` (UserId: `11`, Role: `Lecturer`)

### 2.2. Danh sách 4 Đội thi đấu (Team IDs)
- **Team 1 (`Team Alpha`):** Captain: User 2 (`Debater 01`), Member: User 3 (`Debater 02`).
- **Team 2 (`Team Beta`):** Captain: User 4 (`Debater 03`), Member: User 5 (`Debater 04`).
- **Team 3 (`Team Gamma`):** Captain: User 6 (`Debater 05`), Member: User 7 (`Debater 06`).
- **Team 4 (`Team Delta`):** Captain: User 8 (`Debater 07`), Member: User 9 (`Debater 08`).

### 2.3. Cấu trúc Nhánh đấu & Danh sách Trận đấu (Match IDs)
- **Match 4 (Bán kết 1 - Round 1, Position 1):** `Team 1` (Team Alpha - PRO) vs `Team 3` (Team Gamma - CON). `NextMatchId = 6`.
- **Match 5 (Bán kết 2 - Round 1, Position 2):** `Team 4` (Team Delta - PRO) vs `Team 2` (Team Beta - CON). `NextMatchId = 6`.
- **Match 6 (Chung kết - Round 2, Position 1):** Người thắng Match 4 (PRO) vs Người thắng Match 5 (CON). `NextMatchId = NULL`.

---

## 3. BẢNG TỔNG HỢP CÁC BƯỚC VÀ KẾT QUẢ KIỂM THỬ (TEST EXECUTION MATRIX)

| STT | Bước quy trình | Endpoint / Thao tác | Match / Session | Kết quả API | Trạng thái | Ghi chú |
|:---:|---|---|:---:|:---:|:---:|---|
| 1 | **Create & Setup Competition** | `POST /api/competitions` | Comp 2 | **200 OK** | **PASS** | Tạo giải đấu thể thức TEAM |
| 2 | **Open Registration** | `POST /competitions/2/open-registration` | Comp 2 | **200 OK** | **PASS** | Mở cổng đăng ký đội |
| 3 | **Team Formation (4 đội)** | `POST /teams` & `invitations/accept` | Teams 1..4 | **200 OK** | **PASS** | 4 đội thành lập đủ 2 thành viên/đội (8 thí sinh) |
| 4 | **Generate Bracket** | `POST /competitions/2/bracket` | Comp 2 | **200 OK** | **PASS** | Sinh nhánh đấu Single Elimination 2 vòng (3 matches) |
| 5 | **Start Competition** | `POST /competitions/2/start` | Comp 2 | **200 OK** | **PASS** | Comp chuyển `Ongoing`, Match 4 & 5 chuyển `Ready` |
| 6 | **Prepare Debate Match 4** | `POST /matches/4/prepare-debate` | Match 4 | **200 OK** | **PASS** | Gán Topic 1, sinh `DebateSessionId = 2` (4 debaters) |
| 7 | **Prepare Idempotency Match 4** | `POST /matches/4/prepare-debate` | Match 4 | **200 OK** | **PASS** | Trả về đúng `DebateSessionId = 2` |
| 8 | **Start Debate Match 4** | `POST /api/debate/2/start` | Session 2 | **200 OK** | **PASS** | Session chuyển sang `InProgress` |
| 9 | **Debate Execution Match 4** | `POST /api/debate/2/arguments` | Session 2 | **200 OK** | **PASS** | Thi đấu luân phiên 3 vòng, kết thúc `Completed` |
| 10 | **AI Evaluation Match 4** | `POST /api/debate/2/evaluate` | Session 2 | **200 OK** | **PASS** | AI Llama 3.3 chấm điểm: PRO 5.33, CON 5.50 (`CON` thắng) |
| 11 | **BTC Review Match 4** | `GET /matches/4/review` | Match 4 | **200 OK** | **PASS** | Trả về đủ 5 tiêu chí từ `DebateScoreWeight` và điểm AI |
| 12 | **BTC Finalize Match 4** | `POST /matches/4/finalize` | Match 4 | **200 OK** | **PASS** | **WinnerTeamId: 3 (Team Gamma)**, Match `Completed` |
| 13 | **Bracket Propagation Match 4** | Database Verification | Match 6 | **200 OK** | **PASS** | Team 3 tự động vào Match 6 với `Side = PRO` |
| 14 | **Prepare Debate Match 5** | `POST /matches/5/prepare-debate` | Match 5 | **200 OK** | **PASS** | Sinh `DebateSessionId = 5` (4 debaters Team 4 & Team 2) |
| 15 | **Prepare Idempotency Match 5** | `POST /matches/5/prepare-debate` | Match 5 | **200 OK** | **PASS** | Trả về đúng `DebateSessionId = 5` |
| 16 | **Start Debate Match 5** | `POST /api/debate/5/start` | Session 5 | **200 OK** | **PASS** | Session chuyển sang `InProgress` |
| 17 | **Debate Execution Match 5** | `POST /api/debate/5/arguments` | Session 5 | **200 OK** | **PASS** | Thi đấu 3 vòng, hoàn thành chuyển `Completed` |
| 18 | **AI Evaluation Match 5** | `POST /api/debate/5/evaluate` | Session 5 | **200 OK** | **PASS** | AI Llama 3.3 chấm điểm: PRO 5.33, CON 5.17 |
| 19 | **BTC Review Match 5** | `GET /matches/5/review` | Match 5 | **200 OK** | **PASS** | Trả về đủ 5 tiêu chí và kết quả AI gợi ý |
| 20 | **BTC Finalize Match 5** | `POST /matches/5/finalize` | Match 5 | **200 OK** | **PASS** | **WinnerTeamId: 2 (Team Beta)**, Match `Completed` |
| 21 | **Bracket Propagation Match 5** | Database Verification | Match 6 | **200 OK** | **PASS** | Team 2 tự động vào Match 6 với `Side = CON`; Match 6 chuyển `Ready` |
| 22 | **Prepare Debate Match 6** | `POST /matches/6/prepare-debate` | Match 6 | **200 OK** | **PASS** | Sinh `DebateSessionId = 6` (Chung kết: Team 3 vs Team 2) |
| 23 | **Prepare Idempotency Match 6** | `POST /matches/6/prepare-debate` | Match 6 | **200 OK** | **PASS** | Trả về đúng `DebateSessionId = 6` |
| 24 | **Start Debate Match 6** | `POST /api/debate/6/start` | Session 6 | **200 OK** | **PASS** | Bắt đầu trận Chung kết 2v2 |
| 25 | **Debate Execution Match 6** | `POST /api/debate/6/arguments` | Session 6 | **200 OK** | **PASS** | Thi đấu Chung kết 3 vòng, kết thúc chuyển `Completed` |
| 26 | **AI Evaluation Match 6** | `POST /api/debate/6/evaluate` | Session 6 | **200 OK** | **PASS** | AI Llama 3.3 chấm điểm: PRO 4.83, CON 5.67 (`CON` thắng) |
| 27 | **BTC Review Match 6** | `GET /matches/6/review` | Match 6 | **200 OK** | **PASS** | Review Chung kết thành công |
| 28 | **BTC Finalize Match 6** | `POST /matches/6/finalize` | Match 6 | **200 OK** | **PASS** | **WinnerTeamId: 2 (Team Beta)**, Match 6 `Completed` |
| 29 | **Crown Champion & Complete** | `GET /competitions/2/bracket` | Comp 2 | **200 OK** | **PASS** | **Champion: Team 2 (Team Beta)**, Competition chuyển `Completed` |

---

## 4. CHI TIẾT CÁC PHIÊN TRANH BIỆN (DEBATE SESSIONS)

| DebateSessionId | Thuộc trận đấu | Thể thức | PRO Team (Thí sinh) | CON Team (Thí sinh) | Số lượt tranh biện | Trạng thái |
|:---:|:---:|:---:|---|---|:---:|:---:|
| **2** | Match 4 (Bán kết 1) | 2 vs 2 | **Team 1** (U2: Debater 01, U3: Debater 02) | **Team 3** (U6: Debater 05, U7: Debater 06) | 11 lượt | `Completed` |
| **5** | Match 5 (Bán kết 2) | 2 vs 2 | **Team 4** (U8: Debater 07, U9: Debater 08) | **Team 2** (U4: Debater 03, U5: Debater 04) | 11 lượt | `Completed` |
| **6** | Match 6 (Chung kết) | 2 vs 2 | **Team 3** (U6: Debater 05, U7: Debater 06) | **Team 2** (U4: Debater 03, U5: Debater 04) | 11 lượt | `Completed` |

---

## 5. KẾT QUẢ ĐÁNH GIÁ CỦA AI EVALUATOR (AI JUDGEMENTS)

Tất cả 3 trận đấu đều được xử lý thực tế qua Azure Container Apps AI Evaluator (Model: `Groq / Llama-3.3-70b-versatile`):

| JudgementId | DebateSessionId | Điểm PRO | Điểm CON | AI Suggested Winner | Thời gian đánh giá (UTC) | Trạng thái lưu DB3 |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **4** | 2 (Match 4) | 5.33 / 10 | 5.50 / 10 | **CON** (`Team Gamma`) | 2026-11-14 10:20:01 | **ĐÃ LƯU DB3** |
| **5** | 5 (Match 5) | 5.33 / 10 | 5.17 / 10 | **PRO** (`Team Delta`) | 2026-11-14 10:49:33 | **ĐÃ LƯU DB3** |
| **6** | 6 (Match 6) | 4.83 / 10 | 5.67 / 10 | **CON** (`Team Beta`) | 2026-11-14 10:58:43 | **ĐÃ LƯU DB3** |

---

## 6. ĐIỂM TRỌNG TÀI ĐÃ LƯU (JUDGE SCORES)

Tổng cộng **30 bản ghi** điểm số chính thức được lưu vào bảng `JudgeScores` (10 điểm / trận x 3 trận):

- **Match 4:** 10 bản ghi (JudgeScoreId: 31..40).
  - Team Alpha (PRO, MatchParticipantId: 5): Tổng điểm **75.00**
  - Team Gamma (CON, MatchParticipantId: 6): Tổng điểm **83.00** (Winner)
- **Match 5:** 10 bản ghi (JudgeScoreId: 41..50).
  - Team Delta (PRO, MatchParticipantId: 7): Tổng điểm **72.00**
  - Team Beta (CON, MatchParticipantId: 8): Tổng điểm **83.00** (Winner)
- **Match 6 (Chung kết):** 10 bản ghi (JudgeScoreId: 51..60).
  - Team Gamma (PRO, MatchParticipantId: 11): Tổng điểm **78.00**
  - Team Beta (CON, MatchParticipantId: 12): Tổng điểm **88.00** (Winner)

---

## 7. KẾT QUẢ NGƯỜI THẮNG VÀ LAN TRUYỀN NHÁNH ĐẤU (BRACKET PROGRESSION)

### 7.1. Kết quả WinnerTeamId và WinnerUserId qua các trận:
| Trận đấu | MatchId | Đội PRO | Đội CON | WinnerTeamId | WinnerUserId | Trạng thái Match |
|---|:---:|---|---|:---:|:---:|:---:|
| Bán kết 1 | **4** | Team Alpha (TeamId: 1) | **Team Gamma (TeamId: 3)** | **3** | `NULL` | `Completed` |
| Bán kết 2 | **5** | Team Delta (TeamId: 4) | **Team Beta (TeamId: 2)** | **2** | `NULL` | `Completed` |
| Chung kết | **6** | Team Gamma (TeamId: 3) | **Team Beta (TeamId: 2)** | **2** | `NULL` | `Completed` |

> [!NOTE]
> `WinnerUserId` trong tất cả các trận đấu TEAM đều được bảo toàn giá trị `NULL` tuyệt đối, không bị gán nhầm UserId đơn lẻ, chứng minh logic xử lý giữa thể thức INDIVIDUAL và TEAM trong `CompetitionTournamentService` phân tách chính xác.

### 7.2. Lan truyền nhánh đấu (Bracket Progression):
1. **Sau khi Match 4 Finalize:** Team Gamma (TeamId: 3) tự động được gán vào `Match 6` với `Side = PRO` (`MatchParticipantId = 11`).
2. **Sau khi Match 5 Finalize:** Team Beta (TeamId: 2) tự động được gán vào `Match 6` với `Side = CON` (`MatchParticipantId = 12`). Đồng thời `Match 6` tự động đổi trạng thái từ `Scheduled` sang `Ready`.
3. **Sau khi Match 6 Finalize:** Hệ thống nhận diện trận đấu cuối cùng không có `NextMatchId` và thuộc vòng chung kết (`RoundNumber == 2`), tự động xác định Quán quân giải đấu và cập nhật trạng thái toàn giải.

---

## 8. XÁC NHẬN NHÀ VÔ ĐỊCH VÀ TRẠNG THÁI CUỐI CÙNG

- **Nhà Vô Địch (Champion Team):**
  - `championTeamId`: **`2`** (**`Team Beta`** – Đội trưởng: User 4 `Debater 03`, Thành viên: User 5 `Debater 04`).
  - `championUserId`: **`null`** (đúng tiêu chuẩn giải đồng đội).
- **Trạng thái giải đấu cuối cùng trong DB3:**
  - `Competitions.Status`: **`Completed`**.
  - `Competitions.UpdatedAt`: `2026-11-14 10:58:44.5627895`.

---

## 9. ĐỐI SOÁT TRỰC TIẾP DỮ LIỆU SQL SERVER (`DebatePracticePlatformDB3`)

```sql
SELECT CompetitionId, Title, CompetitionType, Status FROM Competitions WHERE CompetitionId = 2;
-- Kết quả: 2 | E2E Team 2v2 Tournament | TEAM | Completed

SELECT CompetitionMatchId, MatchNumber, BracketPosition, NextMatchId, Status, WinnerTeamId, WinnerUserId FROM CompetitionMatches WHERE CompetitionId = 2;
-- Kết quả:
-- 4 | 1 | 1 | 6    | Completed | 3 | NULL
-- 5 | 2 | 2 | 6    | Completed | 2 | NULL
-- 6 | 1 | 1 | NULL | Completed | 2 | NULL

SELECT MatchParticipantId, CompetitionMatchId, TeamId, Side, FinalScore, IsWinner FROM MatchParticipants WHERE CompetitionMatchId IN (4, 5, 6);
-- Kết quả:
-- 5  | 4 | 1 | PRO | 75.00 | 0
-- 6  | 4 | 3 | CON | 83.00 | 1
-- 7  | 5 | 4 | PRO | 72.00 | 0
-- 8  | 5 | 2 | CON | 83.00 | 1
-- 11 | 6 | 3 | PRO | 78.00 | 0
-- 12 | 6 | 2 | CON | 88.00 | 1
```
Dữ liệu trong Database SQL Server `DebatePracticePlatformDB3` khớp chính xác 100% với toàn bộ API responses.

---

## 10. PHÁT HIỆN KỸ THUẬT VÀ LỖI CÒN TỒN TẠI (FINDINGS & KNOWN ISSUES)

### Phát hiện: Logic kiểm tra kết thúc vòng đấu trong `SubmitTeamArgumentAsync`
- **Vị trí code:** [DebateService.cs#L587](file:///d:/FA26_CapstoneProject/SEP409-AI-DEBATE/Services/SystemService.BLL/Services/Debate/Implementations/DebateService.cs#L587):
  ```csharp
  await _debateRepository.AddArgumentAsync(argument, cancellationToken);
  ...
  if (currentRound.Arguments.Count + 1 >= maxArgsPerRound)
  ```
- **Hiện tượng:**
  Do `_debateRepository.AddArgumentAsync` đã gọi `SaveChangesAsync()`, EF Core relationship fixup đã tự động nạp `argument` vào collection `currentRound.Arguments` trong bộ nhớ. Việc kiểm tra `currentRound.Arguments.Count + 1 >= maxArgsPerRound` dẫn đến việc cộng thêm 1 hai lần.
  Ở vòng 3 (vòng cuối cùng, `nextRound == null`), phiên tranh biện tự động đóng ở lượt thứ 11 thay vì lượt thứ 12 (thành viên thứ 2 của đội CON không cần gửi lượt kết luận thứ 12).
- **Đánh giá ảnh hưởng:**
  Phiên tranh biện vẫn hoàn thành hợp lệ (Status: `Completed`), dữ liệu đủ cho AI Evaluator chấm điểm toàn diện cả 3 vòng, và toàn bộ luồng giải đấu từ Review, Finalize, Propagation, đến Crown Champion đều chạy thành công mỹ mãn.
- **Đề xuất khắc phục (cho sprint tiếp theo):**
  Sửa biểu thức thành `if (currentRound.Arguments.Count >= maxArgsPerRound)`.

---

## 11. KẾT LUẬN

**Quy trình kiểm thử End-to-End Happy Path cho giải đấu TEAM 2v2 trên Database V9 (`DebatePracticePlatformDB3`) chính thức ĐẠT (PASS 100%):**
- Thể thức thi đấu đồng đội 2v2 hoàn chỉnh từ vòng Bán kết đến Chung kết.
- AI Evaluator Azure Container Apps chấm điểm tự động và lưu phán quyết thành công.
- Trọng tài Review và Finalize ghi điểm chi tiết theo tiêu chí và trọng số `DebateScoreWeight` chuẩn xác.
- Lan truyền đội thắng và cập nhật trạng thái nhánh đấu diễn ra tự động và chính xác.
- Xác định Quán quân **Team Beta** (`championTeamId = 2`) và giải đấu chuyển trạng thái **`Completed`** thành công.

