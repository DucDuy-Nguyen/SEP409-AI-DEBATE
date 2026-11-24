# ADPP – PHASE 3 TECHNICAL DESIGN SPECIFICATION (REVISION 3)
## AI Evaluation, BTC Review, Materialized Rubrics, ACCEPT / OVERRIDE & Finalization

**Target Repository:** `D:\FA26_CapstoneProject\SEP409-AI-DEBATE`  
**Execution Mode:** STRICT READ-ONLY AUDIT & DESIGN ONLY  
**Role:** Senior .NET Backend Engineer / Solution Architect  
**Output Document:** `docs/phase-3-technical-design-revision-3.md`  

---

## 1. Git Baseline và Working Tree Verification

- **Branch hiện tại:** `competition` (Trùng khớp 100% với `origin/competition`).
- **Commit hash:** `17cd5ab44b478cf5bf4400d65ed9507073ad1cc9` (*Fix bracket in competition*).
- **Trạng thái Working Tree:**
  - *Files modified (tồn tại từ Phase 0 fix, không có thay đổi mới):*
    - `Services/SystemService.BLL/Services/Debate/Implementations/DebateService.cs`
    - `Services/SystemService.DAL/Configurations/Debate/DebateCriteriaConfiguration.cs`
    - `Services/SystemService/appsettings.json`
    - `Tests/SystemService.IntegrationTests/CompetitionDebateIntegrationTests.cs`
    - `Tests/SystemService.IntegrationTests/DebateAiEvaluatorIntegrationTests.cs`
  - *Untracked documents:* `docs/competition-e2e-v9-db1-report.md`, `docs/competition-e2e-v9-db3-report.md`, `docs/debate-turn-count-fix-report.md`, `docs/team-2v2-e2e-report.md`.
- **Cam kết:** Giữ nguyên 100% working tree, không checkout, không merge, không commit, không can thiệp database hay code.

---

## 2. Verified Current Architecture và Source References

### 2.1. Điểm kích hoạt (Trigger Point)
- **`[VERIFIED]`** [DebateService.cs#L606-L622](file:///d:/FA26_CapstoneProject/SEP409-AI-DEBATE/Services/SystemService.BLL/Services/Debate/Implementations/DebateService.cs#L606-L622):  
  Khi lượt tranh biện cuối cùng hoàn thành trong `SubmitArgumentAsync`:
  ```csharp
  session.Status = SessionStatus.Completed;
  session.EndTime = completedAt;
  await _debateRepository.UpdateLinkedMatchStatusOnSessionCompleteAsync(sessionId, completedAt, cancellationToken);
  await _debateRepository.UpdateSessionAsync(session, cancellationToken);
  ...
  bool isSessionCompleted = session.Status == SessionStatus.Completed;
  await transaction.CommitAsync(cancellationToken);

  if (isSessionCompleted && _aiEvaluatorClient != null)
  {
      StartBackgroundEvaluation(sessionId);
  }
  ```
  Phương thức `UpdateLinkedMatchStatusOnSessionCompleteAsync` cập nhật `CompetitionMatch.Status = "Evaluating"` ([DebateRepository.cs#L235](file:///d:/FA26_CapstoneProject/SEP409-AI-DEBATE/Services/SystemService.DAL/Repositories/Debate/Implementations/DebateRepository.cs#L235)).

### 2.2. Điều phối đánh giá (DebateEvaluationCoordinator)
- **`[VERIFIED]`** [DebateEvaluationCoordinator.cs#L40-L104](file:///d:/FA26_CapstoneProject/SEP409-AI-DEBATE/Services/SystemService.BLL/Services/Debate/Implementations/DebateEvaluationCoordinator.cs#L40-L104):  
  Singleton quản lý `ConcurrentDictionary<int, Lazy<Task<DebateEvaluationResponse>>> _inFlight`. Tạo DI scope riêng biệt (`_scopeFactory.CreateAsyncScope()`) để chạy `EvaluateAndStoreSessionInternalAsync`. Khi có lỗi, khối `finally` tại dòng 78 gọi `_inFlight.TryRemove` để giải phóng key.

### 2.3. Trình tự gọi AI Evaluator
- **`[VERIFIED]`** [DebateService.cs#L1735-L1805](file:///d:/FA26_CapstoneProject/SEP409-AI-DEBATE/Services/SystemService.BLL/Services/Debate/Implementations/DebateService.cs#L1735-L1805):
  1. Lấy toàn bộ rounds đã hoàn thành: `session.DebateRounds.OrderBy(r => r.RoundNumber)`.
  2. Gom turns của mỗi round thành 2 request riêng biệt cho PRO và CON:
     - `proRoundTasks.Add(_aiEvaluatorClient.EvaluateRoundAsync(proRoundReq, cancellationToken));` ([L1766](file:///d:/FA26_CapstoneProject/SEP409-AI-DEBATE/Services/SystemService.BLL/Services/Debate/Implementations/DebateService.cs#L1766))
     - `conRoundTasks.Add(_aiEvaluatorClient.EvaluateRoundAsync(conRoundReq, cancellationToken));` ([L1781](file:///d:/FA26_CapstoneProject/SEP409-AI-DEBATE/Services/SystemService.BLL/Services/Debate/Implementations/DebateService.cs#L1781))
  3. Đợi toàn bộ rounds hoàn thành: `await Task.WhenAll(proRoundTasks.Concat(conRoundTasks));` ([L1786](file:///d:/FA26_CapstoneProject/SEP409-AI-DEBATE/Services/SystemService.BLL/Services/Debate/Implementations/DebateService.cs#L1786)).
  4. Gửi kết quả các rounds đã đánh giá sang `EvaluateSessionAsync`:
     - `_aiEvaluatorClient.EvaluateSessionAsync(new EvaluateSessionRequest(..., Side: "pro", Rounds: proRounds, ...))` ([L1797](file:///d:/FA26_CapstoneProject/SEP409-AI-DEBATE/Services/SystemService.BLL/Services/Debate/Implementations/DebateService.cs#L1797))
     - `_aiEvaluatorClient.EvaluateSessionAsync(new EvaluateSessionRequest(..., Side: "con", Rounds: conRounds, ...))` ([L1800](file:///d:/FA26_CapstoneProject/SEP409-AI-DEBATE/Services/SystemService.BLL/Services/Debate/Implementations/DebateService.cs#L1800))
  5. Đợi session evaluation: `await Task.WhenAll(proSessionTask, conSessionTask);` ([L1802](file:///d:/FA26_CapstoneProject/SEP409-AI-DEBATE/Services/SystemService.BLL/Services/Debate/Implementations/DebateService.cs#L1802)).
  6. Tính điểm trung bình và đề xuất người thắng:
     - `decimal proScore = proSessionRes?.OverallScore ?? AverageWithSkipped(proRounds, proSkipped);` ([L1806](file:///d:/FA26_CapstoneProject/SEP409-AI-DEBATE/Services/SystemService.BLL/Services/Debate/Implementations/DebateService.cs#L1806))
     - `decimal conScore = conSessionRes?.OverallScore ?? AverageWithSkipped(conRounds, conSkipped);` ([L1807](file:///d:/FA26_CapstoneProject/SEP409-AI-DEBATE/Services/SystemService.BLL/Services/Debate/Implementations/DebateService.cs#L1807))
     - `string suggestedWinner = proScore > conScore ? "PRO" : (conScore > proScore ? "CON" : "TIE");` ([L1810-L1812](file:///d:/FA26_CapstoneProject/SEP409-AI-DEBATE/Services/SystemService.BLL/Services/Debate/Implementations/DebateService.cs#L1810-L1812))

### 2.4. Lưu trữ dữ liệu AI hiện tại
- **`[VERIFIED]`** [DebateService.cs#L1826-L1852](file:///d:/FA26_CapstoneProject/SEP409-AI-DEBATE/Services/SystemService.BLL/Services/Debate/Implementations/DebateService.cs#L1826-L1852):
  - Đóng gói JSON thô:
    ```csharp
    var rawData = new { ProSession = proSessionRes, ConSession = conSessionRes, ProRounds = proRounds, ConRounds = conRounds };
    string rawJson = JsonSerializer.Serialize(rawData);
    ```
  - Khởi tạo entity `AIJudgement` và gọi `await _debateRepository.AddAIJudgementAsync(judgement, cancellationToken);`.

---

## 3. Verified Database Schema

### 3.1. Bảng `DebateRounds`
- **`[VERIFIED]`** [DebateRoundConfiguration.cs#L10-L26](file:///d:/FA26_CapstoneProject/SEP409-AI-DEBATE/Services/SystemService.DAL/Configurations/Debate/DebateRoundConfiguration.cs#L10-L26):
  - Khóa chính: `RoundId INT IDENTITY(1,1)` ([DebateRound.cs#L9](file:///d:/FA26_CapstoneProject/SEP409-AI-DEBATE/Services/SystemService.DAL/Entities/Debate/DebateRound.cs#L9)).
  - Khóa ngoại: `DebateSessionId INT` liên kết tới `DebateSessions`. Khóa duy nhất: `UQ (DebateSessionId, RoundNumber)`.
  - Navigation: `CompetitionMatch.DebateSessionId` $\rightarrow$ `DebateSessions.DebateSessionId` $\rightarrow$ `DebateRounds`. Xác định 100% các vòng đấu thuộc một `CompetitionMatch`.

### 3.2. Bảng `DebateScoreWeight` (`DebateCriteria`)
- **`[VERIFIED]`** [DebateCriteriaConfiguration.cs#L11-L24](file:///d:/FA26_CapstoneProject/SEP409-AI-DEBATE/Services/SystemService.DAL/Configurations/Debate/DebateCriteriaConfiguration.cs#L11-L24) & [AIDebate-V0.7.sql#L175-L185](file:///d:/FA26_CapstoneProject/DatabaseSEP/AIDebate-V0.7.sql#L175-L185):
  - Tên bảng vật lý trong SQL Server: `dbo.DebateScoreWeight` (Entity: `DebateCriteria`).
  - Khóa chính: `CriteriaId INT IDENTITY(1,1)`.
  - Cột: `CriteriaName NVARCHAR(100)` (Unique `UQ_DebateCriteria_Name`), `MaxScore DECIMAL(5,2)` (Mặc định 20.00), `Weight DECIMAL(5,4)` (Mặc định 1.0000), `IsActive BIT`.
  - Dữ liệu seed mặc định gồm 5 tiêu chí: `Logic`, `Evidence`, `Relevance`, `Structure`, `Persuasiveness`.

### 3.3. Bảng `JudgeScores` và Ràng buộc `UQ_JudgeScores`
- **`[VERIFIED]`** [AIDebate-V0.7.sql#L1682-L1689](file:///d:/FA26_CapstoneProject/DatabaseSEP/AIDebate-V0.7.sql#L1682-L1689) & [JudgeScoreConfiguration.cs#L14-L16](file:///d:/FA26_CapstoneProject/SEP409-AI-DEBATE/Services/SystemService.DAL/Configurations/Competition/JudgeScoreConfiguration.cs#L14-L16):
  - Trong DDL SQL (`AIDebate-V0.7.sql`), `UQ_JudgeScores` là một **UNIQUE CONSTRAINT**:
    ```sql
    CONSTRAINT UQ_JudgeScores UNIQUE (CompetitionMatchId, JudgeUserId, MatchParticipantId, CriteriaId)
    ```
  - Trong EF Core (`JudgeScoreConfiguration.cs`), cấu hình:
    `builder.HasIndex(e => new { e.CompetitionMatchId, e.JudgeUserId, e.MatchParticipantId, e.CriteriaId }).IsUnique().HasDatabaseName("UQ_JudgeScores");`
  - Cột hiện tại: `JudgeScoreId BIGINT IDENTITY(1,1)`, `CompetitionMatchId INT`, `JudgeUserId INT NOT NULL`, `MatchParticipantId BIGINT NOT NULL`, `CriteriaId INT NOT NULL`, `Score DECIMAL(5,2) NOT NULL`, `Feedback NVARCHAR(MAX) NULL`.
  - Dữ liệu hiện có: Đã xác minh có **60 bản ghi** hợp lệ trong DB3 (toàn bộ đều có `JudgeUserId = 11`, không có `DebateRoundId`).

### 3.4. Bảng `CompetitionMatches` và `MatchParticipants`
- **`[VERIFIED]`** [CompetitionMatchConfiguration.cs#L10-L64](file:///d:/FA26_CapstoneProject/SEP409-AI-DEBATE/Services/SystemService.DAL/Configurations/Competition/CompetitionMatchConfiguration.cs#L10-L64):
  - Khóa chính: `CompetitionMatchId INT IDENTITY(1,1)`. Trạng thái hiện có: `Status NVARCHAR(30)`. Khóa đồng thời: `RowVersion ROWVERSION`.
- **`[VERIFIED]`** [MatchParticipantConfiguration.cs#L14-L20](file:///d:/FA26_CapstoneProject/SEP409-AI-DEBATE/Services/SystemService.DAL/Configurations/Competition/MatchParticipantConfiguration.cs#L14-L20):
  - Ràng buộc duy nhất: `UQ_MatchParticipants_Side (CompetitionMatchId, Side)` $\rightarrow$ **Mỗi trận đấu luôn có chính xác 2 bản ghi `MatchParticipant`: đúng 1 PRO và đúng 1 CON**.
  - `FinalScore DECIMAL(5,2) NULL`, `IsWinner BIT DEFAULT(0)`.
  - Trong 1v1: `UserId` có giá trị, `TeamId` là `NULL`.
  - Trong 2v2: `TeamId` có giá trị, `UserId` là `NULL` (thành viên đội nằm trong `CompetitionTeamMembers`).

---

## 4. Confirmed Business Workflow

1. **Trận đấu kết thúc:** `DebateSession` chuyển sang `Completed`. `CompetitionMatch.Status = "Evaluating"`, `EvaluationStatus = "Pending"`.
2. **AI Evaluation hoàn chỉnh:**
   - Backend gọi `EvaluateRoundAsync` lần lượt/song song cho từng vòng (PRO và CON).
   - Backend gọi `EvaluateSessionAsync` tổng hợp toàn bộ session.
   - AI chỉ đưa ra đề xuất (`SuggestedWinnerSide`), không tự finalize match hay advance bracket.
3. **Dual Persistence trong 1 transaction:**
   - Lưu JSON thô vào `dbo.AIJudgements.RawResponseJson`.
   - Materialize rubric scores vào `dbo.JudgeScores` với `ScoreSource = "AI"`, `JudgeUserId = NULL`, `DebateRoundId = round.RoundId`.
   - Cập nhật `match.EvaluationStatus = "Completed"`.
4. **BTC Review (Độc quyền):**
   - Chỉ BTC (`competition.CreatedBy`) mới có quyền truy cập.
   - Xem AI Summary, Feedback, Suggested Winner, Overall Scores và chi tiết rubric từng vòng đã materialize.
5. **Quyết định của BTC:**
   - **ACCEPT:** BTC chấp nhận bộ điểm AI. Dùng `ScoreSource = "AI"`. Không tạo bản ghi Judge duplicate.
   - **OVERRIDE:** BTC chỉnh sửa điểm rubric từng round. Lưu bộ điểm mới `ScoreSource = "JUDGE"`, giữ nguyên bộ điểm AI. Bắt buộc có `DecisionReason`. Judge có quyền OVERRIDE bất kỳ lúc nào, kể cả khi AI đề xuất PRO, CON hay TIE.
   - **MANUAL_FINALIZE:** Chỉ cho phép khi AI thực sự `Failed` hoặc `TimedOut`, có lý do bắt buộc.
6. **Xác định Winner & Finalize:**
   - Backend tự tính tổng điểm $\sum (\text{Score} \times \text{Weight})$ theo bộ điểm được chọn.
   - Bên có điểm cao hơn thắng (`PRO` hoặc `CON`).
   - Nếu tổng điểm bằng nhau (TIE): Không xác định winner, không advance bracket, yêu cầu BTC điều chỉnh điểm/quyết định.
   - Hoàn tất trận đấu và chuyển winner sang `NextMatch` nguyên tử trong transaction Serializable.

---

## 5. Proposed API Contracts

### 5.1. GET Review
- **Route:** `GET /api/competitions/{competitionId}/matches/{matchId}/review`
- **Quyền hạn:** Bắt buộc `actorId == competition.CreatedBy`. Người ngoài nhận `403 Forbidden`.
- **Response DTO (`MatchReviewResponse`):**

```csharp
public sealed record MatchReviewResponse(
    int MatchId,
    string MatchStatus,              // "Evaluating", "Completed", ...
    int? DebateSessionId,
    // --- Trạng thái tiến trình AI ---
    string EvaluationStatus,         // "Pending" | "Running" | "Completed" | "Failed" | "TimedOut"
    string? EvaluationError,         // Chi tiết lỗi nếu Failed/TimedOut
    // --- Kết quả tổng quan AI ---
    string? AiSuggestedWinnerSide,   // "PRO" | "CON" | "TIE" | null
    decimal? AiScorePro,             // Thang điểm AI tổng quát
    decimal? AiScoreCon,             // Thang điểm AI tổng quát
    string? AiSummary,               // Tóm tắt lập luận của AI
    string? AiOverallFeedback,       // Nhận xét tổng quát của AI
    decimal? AiConfidenceScore,      // Độ tin cậy (0.50 - 1.00)
    // --- Danh sách thí sinh & Tiêu chí ---
    IReadOnlyList<MatchParticipantReview> Participants,
    IReadOnlyList<CriterionReview> Criteria,
    // --- Bảng chi tiết Rubric từng vòng (Materialized từ ScoreSource = "AI") ---
    IReadOnlyList<RoundRubricReviewDto> RoundRubrics
);

public sealed record RoundRubricReviewDto(
    int RoundId,
    int RoundNumber,
    string Stage,                    // "opening", "rebuttal", "closing"
    long MatchParticipantId,
    string Side,                     // "PRO" | "CON"
    int CriteriaId,
    string CriterionCode,            // "LOGIC", "EVIDENCE", ...
    string CriteriaName,
    decimal AiScore,                 // Điểm rubric do AI chấm
    string? AiFeedback               // Nhận xét rubric của AI
);
```

### 5.2. POST Finalize (ACCEPT / OVERRIDE / MANUAL_FINALIZE)
- **Route:** `POST /api/competitions/{competitionId}/matches/{matchId}/finalize`
- **Quyền hạn:** Bắt buộc `actorId == competition.CreatedBy`.
- **Request DTO (`FinalizeMatchRequest`):**

```csharp
public sealed record FinalizeMatchRequest(
    string DecisionType,                                // BẮT BUỘC: "ACCEPT" | "OVERRIDE" | "MANUAL_FINALIZE"
    string? DecisionReason = null,                      // Bắt buộc nếu OVERRIDE hoặc MANUAL_FINALIZE; tùy chọn nếu ACCEPT
    IReadOnlyList<RoundScoreInput>? Scores = null       // Bắt buộc nếu OVERRIDE hoặc MANUAL_FINALIZE; null nếu ACCEPT
);

public sealed record RoundScoreInput(
    int RoundId,
    long MatchParticipantId,
    int CriteriaId,
    decimal Score,
    string? Feedback
);
```

- **Validation Rules:**
  - `DecisionType == "ACCEPT"`:
    - Bắt buộc `EvaluationStatus == "Completed"`.
    - `Scores` phải là `null` hoặc rỗng (chặn nhận điểm thừa từ client).
    - `DecisionReason` là tùy chọn (optional).
  - `DecisionType == "OVERRIDE"`:
    - Bắt buộc `EvaluationStatus == "Completed"`.
    - Bắt buộc `!string.IsNullOrWhiteSpace(DecisionReason)`.
    - `Scores` phải đầy đủ: $\text{Số rounds} \times 2 \text{ bên} \times \text{Số active criteria}$.
  - `DecisionType == "MANUAL_FINALIZE"`:
    - Bắt buộc `EvaluationStatus` thuộc `{"Failed", "TimedOut"}`.
    - Bắt buộc `!string.IsNullOrWhiteSpace(DecisionReason)`.
    - `Scores` phải đầy đủ như OVERRIDE.

---

## 6. Proposed Schema và Migration Strategy

### 6.1. Bảng `dbo.CompetitionMatches`
```sql
ALTER TABLE [dbo].[CompetitionMatches] ADD 
    [EvaluationStatus] NVARCHAR(20) NOT NULL CONSTRAINT [DF_CompetitionMatches_EvaluationStatus] DEFAULT ('Pending'),
    [EvaluationError] NVARCHAR(MAX) NULL,
    [EvaluationStartedAt] DATETIME2 NULL,
    [DecisionType] NVARCHAR(20) NULL,
    [DecisionReason] NVARCHAR(2000) NULL,
    [FinalizedByUserId] INT NULL CONSTRAINT [FK_CompetitionMatches_FinalizedByUser] REFERENCES [dbo].[Users]([UserId]);
```

### 6.2. Bảng `dbo.DebateScoreWeight` (`DebateCriteria`)
Thêm cột `CriterionCode` để cố định contract mapping:
```sql
ALTER TABLE [dbo].[DebateScoreWeight] ADD 
    [CriterionCode] NVARCHAR(50) NULL;

-- Backfill mã tiêu chí cho dữ liệu mặc định
UPDATE [dbo].[DebateScoreWeight] SET [CriterionCode] = 'LOGIC' WHERE [CriteriaName] = 'Logic';
UPDATE [dbo].[DebateScoreWeight] SET [CriterionCode] = 'EVIDENCE' WHERE [CriteriaName] = 'Evidence';
UPDATE [dbo].[DebateScoreWeight] SET [CriterionCode] = 'RELEVANCE' WHERE [CriteriaName] = 'Relevance';
UPDATE [dbo].[DebateScoreWeight] SET [CriterionCode] = 'STRUCTURE' WHERE [CriteriaName] = 'Structure';
UPDATE [dbo].[DebateScoreWeight] SET [CriterionCode] = 'PERSUASIVENESS' WHERE [CriteriaName] = 'Persuasiveness';

ALTER TABLE [dbo].[DebateScoreWeight] ALTER COLUMN [CriterionCode] NVARCHAR(50) NOT NULL;
CREATE UNIQUE NONCLUSTERED INDEX [UQ_DebateCriteria_Code] ON [dbo].[DebateScoreWeight] ([CriterionCode]);
```

### 6.3. Bảng `dbo.JudgeScores`
```sql
ALTER TABLE [dbo].[JudgeScores] ADD 
    [ScoreSource] NVARCHAR(10) NOT NULL CONSTRAINT [DF_JudgeScores_ScoreSource] DEFAULT ('JUDGE'),
    [DebateRoundId] INT NULL CONSTRAINT [FK_JudgeScores_DebateRounds] REFERENCES [dbo].[DebateRounds]([RoundId]);

-- Cho phép JudgeUserId NULL (hỗ trợ ScoreSource = 'AI' mà không dùng fake UserId)
ALTER TABLE [dbo].[JudgeScores] ALTER COLUMN [JudgeUserId] INT NULL;
```

### 6.4. Drop An toàn `UQ_JudgeScores` (Constraint vs Index)
Script kiểm tra động cả `sys.key_constraints` và `sys.indexes`:
```sql
IF EXISTS (SELECT 1 FROM sys.key_constraints WHERE name = 'UQ_JudgeScores' AND parent_object_id = OBJECT_ID('dbo.JudgeScores'))
BEGIN
    ALTER TABLE [dbo].[JudgeScores] DROP CONSTRAINT [UQ_JudgeScores];
END
ELSE IF EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'UQ_JudgeScores' AND object_id = OBJECT_ID('dbo.JudgeScores'))
BEGIN
    DROP INDEX [UQ_JudgeScores] ON [dbo].[JudgeScores];
END;
```

---

## 7. ScoreSource Constraints và Indexes

### 7.1. Database Check Constraints (Bảo vệ tính toàn vẹn ScoreSource)
Để ngăn chặn tình trạng dữ liệu mâu thuẫn ngay từ tầng database, thêm các CHECK constraint:
```sql
-- 1. ScoreSource chỉ chấp nhận 'AI' hoặc 'JUDGE'
ALTER TABLE [dbo].[JudgeScores] ADD CONSTRAINT [CK_JudgeScores_ScoreSource] 
CHECK ([ScoreSource] IN ('AI', 'JUDGE'));

-- 2. Bản ghi AI bắt buộc JudgeUserId = NULL
ALTER TABLE [dbo].[JudgeScores] ADD CONSTRAINT [CK_JudgeScores_AI_JudgeUserId] 
CHECK ([ScoreSource] <> 'AI' OR [JudgeUserId] IS NULL);

-- 3. Bản ghi JUDGE bắt buộc JudgeUserId IS NOT NULL
ALTER TABLE [dbo].[JudgeScores] ADD CONSTRAINT [CK_JudgeScores_Judge_JudgeUserId] 
CHECK ([ScoreSource] <> 'JUDGE' OR [JudgeUserId] IS NOT NULL);

-- 4. Bản ghi AI mới bắt buộc DebateRoundId IS NOT NULL
ALTER TABLE [dbo].[JudgeScores] ADD CONSTRAINT [CK_JudgeScores_AI_RoundId] 
CHECK ([ScoreSource] <> 'AI' OR [DebateRoundId] IS NOT NULL);
```

### 7.2. Ba Filtered Unique Indexes (Đã phân tích tương thích 100%)
```sql
-- 1. Index cho AI Scores theo từng round (Mỗi round/participant/criterion chỉ có DUY NHẤT 1 điểm AI)
CREATE UNIQUE NONCLUSTERED INDEX [UQ_JudgeScores_AI_PerRound]
ON [dbo].[JudgeScores] ([CompetitionMatchId], [MatchParticipantId], [CriteriaId], [DebateRoundId])
WHERE [ScoreSource] = 'AI' AND [DebateRoundId] IS NOT NULL;

-- 2. Index cho Judge Scores theo từng round (Mỗi judge/round/participant/criterion chỉ có DUY NHẤT 1 điểm Judge)
CREATE UNIQUE NONCLUSTERED INDEX [UQ_JudgeScores_Judge_PerRound]
ON [dbo].[JudgeScores] ([CompetitionMatchId], [JudgeUserId], [MatchParticipantId], [CriteriaId], [DebateRoundId])
WHERE [ScoreSource] = 'JUDGE' AND [DebateRoundId] IS NOT NULL;

-- 3. Index tương thích ngược cho dữ liệu cũ (Legacy records có DebateRoundId IS NULL)
CREATE UNIQUE NONCLUSTERED INDEX [UQ_JudgeScores_Legacy_MatchLevel]
ON [dbo].[JudgeScores] ([CompetitionMatchId], [JudgeUserId], [MatchParticipantId], [CriteriaId])
WHERE [DebateRoundId] IS NULL;
```

**`[VERIFIED XÁC NHẬN BẢO TOÀN DỮ LIỆU]`**:
- 60 bản ghi hiện có trong DB3 đều có `JudgeUserId = 11`, `ScoreSource = 'JUDGE'` (theo default constraint), và `DebateRoundId IS NULL`.
- Toàn bộ 60 bản ghi này nằm trọn vẹn trong index số 3 (`UQ_JudgeScores_Legacy_MatchLevel`), không bị ảnh hưởng bởi index số 1 hay số 2.
- Khi AI insert điểm (`ScoreSource = 'AI'`), bản ghi bắt buộc có `DebateRoundId IS NOT NULL` và `JudgeUserId = NULL`, được bảo vệ bởi index số 1.
- Không thể xảy ra xung đột giữa AI và Judge, và không bị lỗi SQL Server khi `JudgeUserId` là `NULL`.

---

## 8. CriterionCode Contract

### 8.1. Hợp đồng Định danh Chuẩn (Stable Contract)
- **Danh mục mã chuẩn:**
  1. `LOGIC`: Tiêu chí tính logic, hợp lý, không ngụy biện.
  2. `EVIDENCE`: Tiêu chí dẫn chứng, số liệu, tính xác thực.
  3. `RELEVANCE`: Tiêu chí bám sát chủ đề kiến nghị và điểm va chạm.
  4. `STRUCTURE`: Tiêu chí bố cục, mạch lạc, quản lý thời gian.
  5. `PERSUASIVENESS`: Tiêu chí sức thuyết phục, nghệ thuật hùng biện.
- **Thay đổi phía AI Evaluator:**  
  Trong response JSON của `evaluate/round`, mỗi tiêu chí trả về thêm thuộc tính `code`:
  ```json
  {
    "code": "LOGIC",
    "name": "Logic",
    "score": 8,
    "reasoning": "Lập luận chặt chẽ..."
  }
  ```

### 8.2. Validation Nghiêm ngặt (Fail-Fast Validation)
Khi materialize điểm AI vào `JudgeScores`:
1. Kiểm tra mỗi round của mỗi phe phải có **đúng chính xác 5 tiêu chí** khớp với 5 active `CriterionCode`.
2. Nếu thiếu tiêu chí, trùng lặp mã hoặc mã không tồn tại trong DB:
   $\rightarrow$ Hủy transaction, **đánh dấu `EvaluationStatus = "Failed"`**, ghi rõ: `EvaluationError = $"AI evaluation returned invalid criteria set for Round {r.RoundNumber}, Side {side}"`.
3. Tuyệt đối không cho phép chuyển sang `Completed` nếu bộ rubric bị khuyết thiếu.

---

## 9. Score Scale 1–10 (Thống nhất Thang điểm)

### 9.1. Quyết định Nghiệp vụ đã Chốt
- AI Evaluator trả về điểm tiêu chí theo thang **1 – 10**.
- Backend thống nhất chuyển sang sử dụng thang **1 – 10**.
- Cập nhật `DebateCriteria.MaxScore = 10.00` (thay vì 20.00 như trước).
- Không tự ý nhân đôi, chia đôi hay quy đổi điểm.

### 9.2. Phân tích Tác động (Impact Analysis)
1. **Dữ liệu hiện tại trong DB3:**
   - 60 bản ghi cũ trong `JudgeScores` có điểm từ 1.00 đến 2.00 (theo test seed cũ). Không có bản ghi nào vượt quá 10.00. Do đó, việc đổi `MaxScore` từ 20 xuống 10 không làm sai lệch hay vi phạm dữ liệu cũ.
2. **Cấu hình & Seed Data:**
   - Cần cập nhật `DebateCriteriaConfiguration.cs`: `builder.Property(e => e.MaxScore).HasDefaultValue(10.0m);`.
   - Migration cập nhật bảng `dbo.DebateScoreWeight`: `UPDATE dbo.DebateScoreWeight SET MaxScore = 10.00;`.
3. **Validation `FinalizeMatchAsync`:**
   - Logic kiểm tra `s.Score >= 0 && s.Score <= c.MaxScore` ([CompetitionTournamentService.cs#L314](file:///d:/FA26_CapstoneProject/SEP409-AI-DEBATE/Services/SystemService.BLL/Services/Competition/Implementations/CompetitionTournamentService.cs#L314)) sẽ tự động áp dụng trần 10.00 cho tất cả các lượt chấm sau này.
4. **Công thức tính `FinalScore`:**
   $$\text{FinalScore}_p = \sum_{r=1}^{\text{Rounds}} \sum_{c \in \text{Criteria}} (\text{Score}_{p, r, c} \times c.\text{Weight})$$
   Với 3 rounds $\times$ 5 criteria (Max 10, Weight 1.0), điểm tối đa của một trận đấu là $3 \times 5 \times 10 = \mathbf{150.00}$ điểm. Cột `MatchParticipants.FinalScore` (`DECIMAL(5, 2)`) lưu trữ tối đa 999.99, hoàn toàn đáp ứng tốt.

---

## 10. Evaluation Lifecycle và Failure Handling

### 10.1. Phân loại Lỗi và Ghi nhận Trung thực
Hệ thống không suy luận lỗi gián tiếp. Mỗi lỗi phải có căn cứ rõ ràng:

| Tình huống thực tế | Trạng thái ghi nhận | Căn cứ xác minh & Hành vi |
| :--- | :--- | :--- |
| **Bắt đầu gọi AI** | `Running` | Ghi `EvaluationStartedAt = DateTime.UtcNow`. Bắt đầu gọi HTTP client. |
| **HTTP Timeout thực sự** | `TimedOut` | Bắt được `TimeoutException` hoặc `TaskCanceledException` từ `_aiEvaluatorClient`. Ghi `EvaluationError = "AI Evaluator HTTP request timed out."`. |
| **HTTP Error (4xx/5xx)** | `Failed` | Bắt được `HttpRequestException` (ví dụ: HTTP 500 từ container). Ghi `EvaluationError = $"AI Evaluator returned HTTP {statusCode}: {body}"`. |
| **JSON Parse Error** | `Failed` | Bắt được `JsonException` (AI trả về JSON sai format). Ghi `EvaluationError = $"JSON parse error: {ex.Message}"`. |
| **DB Save Error** | `Failed` | Bắt được `DbUpdateException` / `SqlException` khi materialize điểm. Rollback sạch transaction, ghi `EvaluationError = $"DB persistence error: {ex.Message}"`. |
| **Shutdown Cancellation** | Giữ nguyên `Running` | Bắt được `stoppingToken.IsCancellationRequested`. **Tuyệt đối không gán `Failed` hay `TimedOut`**. |

### 10.2. Xử lý App Restart khi trạng thái đang `Running`
- **Thực tế kiến trúc:** Hệ thống không có Worker hay Sweeper chạy ngầm. Khi app restart, in-memory coordinator mất task, nhưng bản ghi trong DB vẫn là `Running`.
- **Nguyên tắc trung thực:**  
  Không thể tự động suy luận app crash nghĩa là AI failed. Do đó, khi BTC gọi `GET review`:
  - Nếu `match.EvaluationStatus == "Running"` và task không còn trong coordinator:
    API trả về `EvaluationStatus = "Running"`, kèm thông báo cảnh báo:  
    `"Evaluation process was interrupted by an application restart. Please click 'Retry' to trigger evaluation."`.
  - **Tuyệt đối không tự động gán `Failed` hay `TimedOut`**, và **không tự động mở quyền `MANUAL_FINALIZE`**.
  - BTC chỉ có thể bấm **"Retry Evaluation"** (`POST /api/debate/{sessionId}/evaluate`).
  - Chỉ khi lượt gọi Retry đó thực sự trả về lỗi HTTP 500 hoặc Timeout, hệ thống mới chuyển `EvaluationStatus` sang `Failed`/`TimedOut` và khi đó mới đủ điều kiện cho phép `MANUAL_FINALIZE`.

---

## 11. Transaction Boundary và Retry/Idempotency

### 11.1. Hiện trạng Khảo sát Repository & DbContext
- **`[VERIFIED]`** [DebateRepository.cs#L20-L24](file:///d:/FA26_CapstoneProject/SEP409-AI-DEBATE/Services/SystemService.DAL/Repositories/Debate/Implementations/DebateRepository.cs#L20-L24): `DebateRepository` nhận `SystemDbContext _context`.
- **`[VERIFIED]`** [DebateRepository.cs#L321-L322](file:///d:/FA26_CapstoneProject/SEP409-AI-DEBATE/Services/SystemService.DAL/Repositories/Debate/Implementations/DebateRepository.cs#L321-L322): `AddAIJudgementAsync` gọi `await _context.SaveChangesAsync(cancellationToken);`.
- **`[VERIFIED]`** [DebateRepository.cs#L202-L209](file:///d:/FA26_CapstoneProject/SEP409-AI-DEBATE/Services/SystemService.DAL/Repositories/Debate/Implementations/DebateRepository.cs#L202-L209): `DebateRepository` cung cấp `BeginTransactionAsync(IsolationLevel, ct)` và `ClearChangeTracker()`.

### 11.2. Thiết kế Transaction Nguyên tử cho Dual Persistence
Toàn bộ thao tác lưu AI Judgement, materialize AI JudgeScores và cập nhật `EvaluationStatus = "Completed"` phải cùng chung 1 transaction:

```csharp
await using var tx = await _debateRepository.BeginTransactionAsync(IsolationLevel.ReadCommitted, cancellationToken);
try
{
    // 1. Lưu AIJudgement (chứa RawResponseJson)
    // Lưu ý: AddAIJudgementAsync gọi SaveChangesAsync, thao tác này vẫn nằm trong tx
    await _debateRepository.AddAIJudgementAsync(judgement, cancellationToken);

    // 2. Materialize AI Rubric Scores vào dbo.JudgeScores
    await _debateRepository.AddJudgeScoresAsync(aiJudgeScores, cancellationToken);

    // 3. Cập nhật EvaluationStatus của Match
    await _debateRepository.UpdateMatchEvaluationStatusAsync(
        matchId, "Completed", error: null, cancellationToken);

    // 4. Commit nguyên tử cả 3 thao tác
    await tx.CommitAsync(cancellationToken);
}
catch (Exception ex)
{
    await tx.RollbackAsync(cancellationToken);

    // QUAN TRỌNG: Xóa sạch ChangeTracker để tránh lỗi re-saving faulted entities
    _debateRepository.ClearChangeTracker();

    // Ghi nhận trạng thái thất bại ra ngoài transaction bị rollback
    string failStatus = (ex is TimeoutException or TaskCanceledException) ? "TimedOut" : "Failed";
    await _debateRepository.UpdateMatchEvaluationStatusAsync(
        matchId, failStatus, ex.Message, CancellationToken.None);

    throw;
}
```

### 11.3. Cơ chế Chống Trùng lặp khi Retry (Idempotency)
Nếu trước đó đã có một lần evaluate bị lỗi nửa chừng hoặc retry lại:
- Trước khi chèn bản ghi mới:
  `DELETE FROM dbo.JudgeScores WHERE CompetitionMatchId = @matchId AND ScoreSource = 'AI';`
  `DELETE FROM dbo.AIJudgements WHERE DebateSessionId = @sessionId;`
  Thao tác xóa dọn dẹp này nằm ngay trong transaction đầu hàm trước khi insert bản ghi mới. Đảm bảo retry bao nhiêu lần cũng không bao giờ sinh ra duplicate AI scores.

---

## 12. PRO/CON Mapping cho 1v1 và 2v2

- **`[VERIFIED]`** Ràng buộc `UQ_MatchParticipants_Side` ([MatchParticipantConfiguration.cs#L14-L16](file:///d:/FA26_CapstoneProject/SEP409-AI-DEBATE/Services/SystemService.DAL/Configurations/Competition/MatchParticipantConfiguration.cs#L14-L16)):  
  Trong mọi thể thức (1v1 và 2v2), bảng `MatchParticipants` **luôn luôn có đúng 2 bản ghi** cho một trận đấu:
  1. Bản ghi với `Side = "PRO"`:
     - 1v1: Đại diện cho cá nhân thí sinh PRO (`UserId` có giá trị, `TeamId = null`).
     - 2v2: Đại diện cho đội PRO (`TeamId` có giá trị, `UserId = null`).
  2. Bản ghi với `Side = "CON"`:
     - 1v1: Đại diện cho cá nhân thí sinh CON (`UserId` có giá trị, `TeamId = null`).
     - 2v2: Đại diện cho đội CON (`TeamId` có giá trị, `UserId = null`).
- **Ánh xạ Điểm AI:**
  - AI Evaluator chấm điểm phân biệt theo `side = "pro"` và `side = "con"` ([DebateService.cs#L1763, L1778](file:///d:/FA26_CapstoneProject/SEP409-AI-DEBATE/Services/SystemService.BLL/Services/Debate/Implementations/DebateService.cs#L1763)).
  - Điểm `side = "pro"` map chính xác 1-1 vào `MatchParticipantId` có `Side == "PRO"`.
  - Điểm `side = "con"` map chính xác 1-1 vào `MatchParticipantId` có `Side == "CON"`.
- **Tính điểm cho 2v2:** Điểm của phe `PRO` (hoặc `CON`) là điểm đại diện cho cả đội, được gán vào `MatchParticipant.FinalScore` của đội đó. Không chia nhỏ `FinalScore` cho từng cá nhân trong đội.

---

## 13. ACCEPT / OVERRIDE / MANUAL_FINALIZE (Quy tắc Nghiệp vụ)

### 13.1. Luồng ACCEPT
- **Điều kiện:** `EvaluationStatus == "Completed"`.
- **Hành động:**
  - Lấy bộ điểm `ScoreSource = "AI"` từ `dbo.JudgeScores`.
  - Không tạo thêm bất kỳ dòng Judge nào.
  - Lưu `match.DecisionType = "ACCEPT"`, `match.DecisionReason = request.DecisionReason` (tùy chọn).
  - Tính tổng điểm $\sum (\text{Score} \times \text{Weight})$ cho PRO và CON $\rightarrow$ Xác định Winner.

### 13.2. Luồng OVERRIDE
- **Điều kiện:**
  - `EvaluationStatus == "Completed"`.
  - Bắt buộc có `DecisionReason` không được rỗng.
  - Judge có quyền OVERRIDE **bất cứ lúc nào**, không phụ thuộc AI đề xuất PRO, CON hay TIE.
  - Client gửi mảng `Scores` đầy đủ theo từng round ($\text{rounds} \times 2 \text{ sides} \times \text{criteria}$).
- **Hành động:**
  - Lưu các dòng mới vào `dbo.JudgeScores` với `ScoreSource = "JUDGE"`, `JudgeUserId = actorId`, `DebateRoundId = r.RoundId`.
  - **Giữ nguyên 100% các dòng `ScoreSource = "AI"`**.
  - Lưu `match.DecisionType = "OVERRIDE"`, `match.DecisionReason = request.DecisionReason.Trim()`.
  - Tính tổng điểm từ bộ điểm `JUDGE` $\rightarrow$ Xác định Winner.

### 13.3. Luồng MANUAL_FINALIZE
- **Điều kiện:**
  - Chỉ được gọi khi `EvaluationStatus` thực sự là `"Failed"` hoặc `"TimedOut"` (có lỗi được lưu trong `EvaluationError`).
  - Bắt buộc có `DecisionReason` giải thích lý do khẩn cấp.
  - Client gửi mảng `Scores` đầy đủ như OVERRIDE.
- **Hành động:**
  - Lưu các dòng vào `dbo.JudgeScores` với `ScoreSource = "JUDGE"`.
  - Lưu `match.DecisionType = "MANUAL_FINALIZE"`, `match.DecisionReason = request.DecisionReason.Trim()`.
  - Tính tổng điểm từ bộ điểm `JUDGE` $\rightarrow$ Xác định Winner.

---

## 14. Atomic Finalization và Bracket Advancement

Toàn bộ thao tác thực hiện trong transaction `IsolationLevel.Serializable` tại `CompetitionTournamentService.FinalizeMatchAsync`:

1. **Tuần tự hóa:** Gọi `await LockCompetitionAsync(competitionId, ct);` với hint `UPDLOCK, HOLDLOCK`.
2. **Khóa Match:** Đọc `match` và kiểm tra `match.Status == "Evaluating"` (ngăn chặn finalize 2 lần).
3. **Validation Dữ liệu:**
   - Validate đầy đủ số lượng điểm: $\text{rounds} \times 2 \times \text{active criteria}$.
   - Validate từng `RoundId`, `MatchParticipantId`, `CriteriaId` phải thuộc đúng `match` này.
4. **Tính điểm và Phán quyết Winner hoàn toàn tự động:**
   $$\text{FinalScore}_{\text{PRO}} = \sum_{r} \sum_{c} (\text{Score}_{\text{PRO}, r, c} \times c.\text{Weight})$$
   $$\text{FinalScore}_{\text{CON}} = \sum_{r} \sum_{c} (\text{Score}_{\text{CON}, r, c} \times c.\text{Weight})$$
   - Nếu $\text{FinalScore}_{\text{PRO}} > \text{FinalScore}_{\text{CON}} \rightarrow \text{Winner} = \text{PRO}$.
   - Nếu $\text{FinalScore}_{\text{CON}} > \text{FinalScore}_{\text{PRO}} \rightarrow \text{Winner} = \text{CON}$.
   - **Xử lý TIE:** Nếu $\text{FinalScore}_{\text{PRO}} == \text{FinalScore}_{\text{CON}}$, **tuyệt đối không xác định winner, không advance bracket**, ném lỗi `400 Bad Request: "Match resulted in a tie. BTC must adjust scores via OVERRIDE to resolve the tie."`.
5. **Cập nhật Trận đấu & Cây thi đấu:**
   - `proParticipant.FinalScore = totals[proId]; proParticipant.IsWinner = (winner == proParticipant);`
   - `conParticipant.FinalScore = totals[conId]; conParticipant.IsWinner = (winner == conParticipant);`
   - `match.WinnerUserId = winner.UserId; match.WinnerTeamId = winner.TeamId; match.Status = "Completed";`
   - Đẩy Winner vào `NextMatch.Participants` (kiểm tra `!next.Participants.Any(p => p.Side == targetSide)` để chống đẩy lặp).
   - Nếu là trận chung kết $\rightarrow$ `competition.Status = "Completed"`.
   - `await _context.SaveChangesAsync(ct); await tx.CommitAsync(ct);`

---

## 15. Test Plan

| Mã Test | Môi trường | Kịch bản kiểm thử | Kỳ vọng |
| :--- | :--- | :--- | :--- |
| **TC-SEC-01** | `[AUTO]` | Non-BTC Review | User khác gọi `GET review` $\rightarrow$ Nhận `403 Forbidden`. |
| **TC-SEC-02** | `[SQLDEV]` | Non-BTC Finalize | User khác gọi `POST finalize` $\rightarrow$ Nhận `403 Forbidden`. |
| **TC-MAT-01** | `[SQLDEV]` | Materialize AI Rubrics | Sau debate, kiểm tra `JudgeScores` có đủ 30 dòng (3 rounds $\times$ 2 sides $\times$ 5 criteria) với `ScoreSource = 'AI'`, `JudgeUserId = NULL`. |
| **TC-ACC-01** | `[SQLDEV]` | ACCEPT thành công | BTC gọi ACCEPT $\rightarrow$ 0 bản ghi Judge được tạo, tính đúng `FinalScore`, winner được đẩy sang `NextMatch`. |
| **TC-OVR-01** | `[SQLDEV]` | OVERRIDE thành công khi AI đề xuất TIE | AI đề xuất TIE, BTC gửi OVERRIDE kèm điểm và lý do $\rightarrow$ Thành công, lưu bộ điểm Judge, xác định winner theo điểm Judge. |
| **TC-OVR-02** | `[AUTO]` | Từ chối OVERRIDE thiếu lý do | Gửi OVERRIDE với `DecisionReason = ""` $\rightarrow$ Nhận `400 Bad Request`. |
| **TC-TIE-01** | `[SQLDEV]` | Chặn Finalize khi điểm bằng nhau | Tổng điểm sau tính toán hòa nhau $\rightarrow$ Nhận `400 Bad Request`, không advance bracket. |
| **TC-MAN-01** | `[SQLDEV]` | MANUAL_FINALIZE hợp lệ | `EvaluationStatus = "Failed"`, BTC gửi điểm và lý do khẩn cấp $\rightarrow$ Thành công. |
| **TC-MAN-02** | `[AUTO]` | Chặn MANUAL_FINALIZE khi AI chưa lỗi | `EvaluationStatus = "Running"`, BTC gọi MANUAL_FINALIZE $\rightarrow$ Nhận `400 Bad Request`. |
| **TC-CON-01** | `[SQLDEV]` | Concurrency Protection | 2 request Finalize đồng thời $\rightarrow$ Đúng 1 request thành công (200 OK), request 2 nhận `409 Conflict`. Bracket chỉ tiến 1 lần. |

---

## 16. Implementation Plan theo từng bước (Có Phụ thuộc Rõ ràng)

```
[Bước 1: Cập nhật DAL Entities & Configurations]
  │  Files: CompetitionMatch.cs, CompetitionMatchConfiguration.cs,
  │         JudgeScore.cs, JudgeScoreConfiguration.cs,
  │         DebateCriteria.cs, DebateCriteriaConfiguration.cs
  ▼
[Bước 2: Tạo EF Core Migration]
  │  Thực thi: dotnet ef migrations add AddRoundRubricScoresAndEvaluationStatus
  │  Kiểm tra Up() / Down() và drop an toàn UQ_JudgeScores
  ▼
[Bước 3: Cập nhật DebateRepository & DebateService (Dual Persistence)]
  │  Files: DebateRepository.cs, IDebateRepository.cs, DebateService.cs
  │  Thực thi: Transaction lưu AIJudgement + materialize AI JudgeScores + EvaluationStatus
  ▼
[Bước 4: Cập nhật DTOs & CompetitionTournamentService]
  │  Files: TournamentDtos.cs, CompetitionTournamentService.cs
  │  Thực thi: GET Review (trả về rubric matrix), POST Finalize (ACCEPT, OVERRIDE, MANUAL_FINALIZE)
  ▼
[Bước 5: Viết & Chạy Bộ Test Suite]
     Files: SqlServerCompetitionDebateTests.cs, CompetitionDebateIntegrationTests.cs
```

---

## 17. Remaining Blockers

1. **`[BLOCKER 1 - CẦN THỐNG NHẤT HỢP ĐỒNG AI SERVICE]` Cung cấp `code` trong `CriterionScoreDto`:**  
   Cần đội ngũ AI Evaluator cam kết trả về `code` trong mảng criteria của mỗi round (hoặc đảm bảo trường `name` luôn khớp chính xác 5 chuỗi: `"Logic"`, `"Evidence"`, `"Relevance"`, `"Structure"`, `"Persuasiveness"`).
2. **`[BLOCKER 2 - CẦN XÁC NHẬN TRIỂN KHAI]` Cập nhật `MaxScore = 10.00`:**  
   Xác nhận việc cập nhật `DebateScoreWeight.MaxScore = 10.00` trong DB3 và seed data để đồng nhất hoàn toàn thang điểm với AI Evaluator.

---

> [!IMPORTANT]
> **BÁO CÁO KẾT THÚC VÀ TUÂN THỦ READ-ONLY:**  
> - **File tài liệu đã tạo:** `docs/phase-3-technical-design-revision-3.md` (Tạo mới, không ghi đè bất kỳ file cũ nào).  
> - **Git Status Verification:** Working tree và branch được bảo toàn tuyệt đối, không có lệnh code, migration hay git commit nào được thực thi.  
> - **Dừng lại chờ phê duyệt:** Kính đề nghị người dùng kiểm tra tài liệu và phê duyệt để chuyển sang bước triển khai.

