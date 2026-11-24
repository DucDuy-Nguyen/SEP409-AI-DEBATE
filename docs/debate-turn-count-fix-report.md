# Báo Cáo Xử Lý Bug Đếm Lượt Tranh Biện (Debate Turn Count Fix Report)

## 1. Thông Tin Tổng Quan
- **Mã Task:** Phase 0 – Fix Final Debate Turn Bug
- **Hệ thống:** ADPP – AI Debate Practice Platform
- **File sửa đổi chính:**
  - `Services/SystemService.BLL/Services/Debate/Implementations/DebateService.cs`
  - `Tests/SystemService.IntegrationTests/CompetitionDebateIntegrationTests.cs`
  - `Tests/SystemService.IntegrationTests/DebateAiEvaluatorIntegrationTests.cs`
- **Ngày thực hiện:** 14/11/2026

---

## 2. Phân Tích Nguyên Nhân Gốc Rễ (Root Cause Analysis)

### 2.1. Hiện tượng
- Trong trận đấu tranh biện 2v2 (3 rounds x 4 turns = 12 turns), khi người nói thứ 11 nộp lượt phản biện (Turn 11, Round 3), hệ thống kết thúc phiên tranh biện ngay lập tức (`session.Status = SessionStatus.Completed`).
- Khi người nói thứ 12 nộp bài, API trả về mã lỗi HTTP 400: `SESSION_NOT_IN_PROGRESS` ("Debate session is not currently in progress").
- Trận đấu bị mất lượt tranh luận cuối cùng của đội CON.

### 2.2. Cơ chế gây lỗi trong EF Core
Tại phương thức `SubmitTeamArgumentAsync`:
```csharp
// Dòng 581:
await _debateRepository.AddArgumentAsync(argument, cancellationToken);
```
1. `_debateRepository.AddArgumentAsync` thực hiện `_context.Arguments.AddAsync(argument)` và `await _context.SaveChangesAsync()`.
2. Khi `SaveChangesAsync()` chạy, EF Core kích hoạt cơ chế quan hệ **Navigation Fixup**: Do `argument.RoundId == currentRound.RoundId` và thực thể `currentRound` đang được theo dõi (tracked) trong DbContext, EF Core tự động thêm `argument` vào collection `currentRound.Arguments`.
3. Do đó, ngay sau dòng 581, `currentRound.Arguments.Count` đã tăng thêm 1 và phản ánh đúng số lượt trong round.
4. Tuy nhiên, tại dòng 587 (trước khi sửa):
```csharp
if (currentRound.Arguments.Count + 1 >= maxArgsPerRound) // maxArgsPerRound = 4
```
Điều kiện này cộng thêm `+ 1` một lần nữa, dẫn đến việc kiểm tra bị lệch (off-by-one / double-counting):
- Lượt 1: Count = 1 -> `1 + 1 = 2 >= 4` (False)
- Lượt 2: Count = 2 -> `2 + 1 = 3 >= 4` (False)
- Lượt 3: Count = 3 -> `3 + 1 = 4 >= 4` (**TRUE!**)
  - Hệ thống đóng Round sớm và gán `nextRound.StartTime`.
  - Nhưng do Round 1 & Round 2 có `nextRound != null`, ở lượt 4, câu truy vấn `session.DebateRounds.FirstOrDefault(r => r.Arguments.Count < maxArgsPerRound)` vẫn trả về Round 1 (vì 3 < 4), cho phép lượt 4 lọt vào round.
  - Tuy nhiên, tại **Round 3** (round cuối cùng, `nextRound == null`), khi Lượt 11 được nộp (Lượt thứ 3 của Round 3):
    - `currentRound.Arguments.Count` đã là 3.
    - Điều kiện `3 + 1 >= 4` lập tức thỏa mãn nhánh `else` (`nextRound == null`):
      ```csharp
      session.Status = SessionStatus.Completed;
      session.EndTime = completedAt;
      await _debateRepository.UpdateLinkedMatchStatusOnSessionCompleteAsync(sessionId, completedAt, cancellationToken);
      ```
    - Phiên tranh biện bị đóng hoàn toàn tại Lượt 11, chặn đứng Lượt 12!

### 2.3. Audit 1v1 Individual Debate
- 1v1 Individual Debate sử dụng phương thức `AddTurnArgumentAsync` và lớp `DebateTurnOrder`.
- Tại dòng 316-317:
  ```csharp
  int submittedCount = CountArguments(session);
  var nextTurn = DebateTurnOrder.GetNextTurn(submittedCount);
  ```
- Dòng 960:
  ```csharp
  var followingTurn = DebateTurnOrder.GetNextTurn(submittedCount + 1);
  if (followingTurn != null && followingTurn.RoundNumber == turn.RoundNumber) return argument;
  ```
- 1v1 không sử dụng `round.Arguments.Count + 1`, mà sử dụng biến đếm độc lập `submittedCount + 1` được tính trước khi insert. Do đó, **1v1 Individual Debate hoàn toàn không bị ảnh hưởng bởi lỗi này**.

---

## 3. Giải Pháp Đã Triển Khai (Fix Implementation)

Tại `DebateService.cs`, cập nhật logic xác định kết thúc round:
```csharp
await _debateRepository.AddArgumentAsync(argument, cancellationToken);
if (request.DeliveryAnalytics != null && argument.ArgumentId > 0)
{
    _argumentDeliveryAnalytics[argument.ArgumentId] = request.DeliveryAnalytics;
}

// Đảm bảo argument luôn có mặt trong collection kể cả trong môi trường mock/in-memory không có EF Core fixup
if (!currentRound.Arguments.Contains(argument))
{
    currentRound.Arguments.Add(argument);
}

// Sửa dứt điểm double-counting: so sánh trực tiếp Count với maxArgsPerRound
if (currentRound.Arguments.Count >= maxArgsPerRound)
{
    currentRound.EndTime = DateTime.UtcNow;
    await _debateRepository.UpdateRoundAsync(currentRound, cancellationToken);

    var nextRound = session.DebateRounds.FirstOrDefault(r => r.RoundNumber == currentRound.RoundNumber + 1);
    if (nextRound != null)
    {
        nextRound.StartTime = DateTime.UtcNow;
        await _debateRepository.UpdateRoundAsync(nextRound, cancellationToken);
    }
    else
    {
        var completedAt = DateTime.UtcNow;
        session.Status = SessionStatus.Completed;
        session.EndTime = completedAt;
        await _debateRepository.UpdateLinkedMatchStatusOnSessionCompleteAsync(sessionId, completedAt, cancellationToken);
        await _debateRepository.UpdateSessionAsync(session, cancellationToken);
    }
}
```

---

## 4. Kiểm Thử & Xác Minh (Verification & Regression Tests)

### 4.1. Unit & Integration Tests Bổ Sung
Đã bổ sung 2 bài test tự động chuyên biệt vào `CompetitionDebateIntegrationTests.cs`:
1. `Test13_Team2v2_Exactly12Turns_CompletesOn12thTurn_Rejects13thTurn`:
   - Mô phỏng trận đấu 2v2 với 4 người tham gia (2 đội PRO & CON).
   - Nộp tuần tự 12 lượt qua 3 round (mỗi round 4 lượt: PRO-1, CON-1, PRO-2, CON-2).
   - Xác nhận:
     - Các lượt từ 1 đến 11: `Status == InProgress`.
     - Lượt thứ 12: `Status == Completed`, `Match.Status == Evaluating`.
     - Lượt thứ 13: Bị từ chối với `Success == false`.
     - Database lưu đủ chính xác 12 arguments (4 arguments/round).
     - Argument cuối cùng thuộc về người nói thứ 2 của đội CON tại Round 3.
2. `Test14_Individual1v1_Exactly6Turns_CompletesOn6thTurn_Rejects7thTurn`:
   - Mô phỏng trận đấu 1v1 cá nhân.
   - Nộp đúng theo thứ tự `DebateTurnOrder`:
     - Round 1: PRO, CON
     - Round 2: PRO, CON
     - Round 3: CON, PRO (Closing round kết thúc bởi PRO)
   - Xác nhận:
     - Lượt 1 đến 5: `Status == InProgress`.
     - Lượt 6: `Status == Completed`.
     - Lượt 7: Bị từ chối.
     - Database lưu đủ 6 arguments (2 arguments/round).

### 4.2. Kết quả kiểm thử
- `CompetitionDebateIntegrationTests`: **20/20 PASSED** (0 Failed, 0 Skipped).
- `SystemService.Tests`: **120/120 PASSED** (0 Failed, 0 Skipped).
- Không có hồi quy (regression) đối với các module hiện hữu.

---

## 5. Kết Luận
Bug đếm lượt tranh biện đã được khắc phục hoàn toàn, đảm bảo tính toàn vẹn và công bằng cho các giải đấu 2v2 TEAM và 1v1 INDIVIDUAL. Hệ thống đã sẵn sàng để tiếp tục triển khai Phase 3.

