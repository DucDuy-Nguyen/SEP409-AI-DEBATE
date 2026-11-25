/* ============================================================
   ADPP CREDIT SYSTEM UPDATE & SEED SCRIPT (NON-DESTRUCTIVE)
   - Preserves all Wallets, WalletTransactions, PaymentTransactions, RewardClaims
   - Updates / inserts the 3 official CreditPackages (BASIC, STANDARD, PREMIUM)
   - Deactivates test package 111 (keeps history intact, sets IsActive = 0)
   - Updates / inserts active CreditRules for AI Practice, AI Hint, and Competition
   - Disables legacy P2P_MATCH_PER_USER rule without deleting history
   - Preserves existing reward rules (FIRST_LOGIN, DAILY_LOGIN)

   Execution notes:
   - File is encoded as UTF-8 with BOM to ensure Unicode characters are preserved in SSMS and sqlcmd.
   - Command line: sqlcmd -S (local)\SQLEXPRESS -d DebatePracticePlatformDB -f 65001 -i CreditSystem-Update-Seed.sql
   ============================================================ */

USE [DebatePracticePlatformDB];
GO

SET NOCOUNT ON;
SET XACT_ABORT ON;

BEGIN TRY
    BEGIN TRANSACTION;

    /* 1. CreditPackages: BASIC (20K -> 2000), STANDARD (50K -> 5200), PREMIUM (100K -> 11000) */
    MERGE dbo.CreditPackages AS target
    USING (VALUES
        (N'BASIC',    N'Gói Cơ Bản (Basic)',       CAST(20000.00 AS DECIMAL(18,2)),  N'VND', CAST(2000 AS BIGINT),  CAST(0 AS BIGINT), CAST(1 AS BIT)),
        (N'STANDARD', N'Gói Tiêu Chuẩn (Standard)', CAST(50000.00 AS DECIMAL(18,2)),  N'VND', CAST(5200 AS BIGINT),  CAST(0 AS BIGINT), CAST(1 AS BIT)),
        (N'PREMIUM',  N'Gói Cao Cấp (Premium)',     CAST(100000.00 AS DECIMAL(18,2)), N'VND', CAST(11000 AS BIGINT), CAST(0 AS BIGINT), CAST(1 AS BIT))
    ) AS source (PackageCode, PackageName, Price, Currency, CreditAmount, BonusCredit, IsActive)
    ON target.PackageCode = source.PackageCode
    WHEN MATCHED THEN
        UPDATE SET
            target.PackageName  = source.PackageName,
            target.Price        = source.Price,
            target.Currency     = source.Currency,
            target.CreditAmount = source.CreditAmount,
            target.BonusCredit  = source.BonusCredit,
            target.IsActive     = source.IsActive,
            target.UpdatedAt    = SYSUTCDATETIME()
    WHEN NOT MATCHED THEN
        INSERT (PackageCode, PackageName, Price, Currency, CreditAmount, BonusCredit, IsActive, CreatedAt)
        VALUES (source.PackageCode, source.PackageName, source.Price, source.Currency, source.CreditAmount, source.BonusCredit, source.IsActive, SYSUTCDATETIME());

    /* Deactivate test package 111 if present (do not delete physically to preserve 32+ payment transactions) */
    UPDATE dbo.CreditPackages
    SET IsActive = 0,
        UpdatedAt = SYSUTCDATETIME()
    WHERE PackageCode = N'111';

    /* 2. CreditRules: Usage pricing + preserve existing reward rules */
    MERGE dbo.CreditRules AS target
    USING (VALUES
        (N'AI_PRACTICE_MATCH',  CAST(150 AS BIGINT),  N'Phí luyện tập tranh biện với AI có kiểm chứng RAG (mỗi trận)', CAST(1 AS BIT)),
        (N'AI_PRACTICE_NO_RAG', CAST(110 AS BIGINT),  N'Phí luyện tập tranh biện với AI không dùng RAG (mỗi trận)',   CAST(1 AS BIT)),
        (N'AI_HINT',            CAST(5 AS BIGINT),    N'Phí sử dụng AI Hint / Hướng dẫn lập luận (mỗi lần)',          CAST(1 AS BIT)),
        (N'COMPETITION_SMALL',  CAST(500 AS BIGINT),  N'Phí tạo Competition nhỏ (tối đa 8 cá nhân hoặc 4 đội)',       CAST(1 AS BIT)),
        (N'COMPETITION_MEDIUM', CAST(1200 AS BIGINT), N'Phí tạo Competition vừa (tối đa 16 cá nhân hoặc 8 đội)',      CAST(1 AS BIT)),
        (N'COMPETITION_LARGE',  CAST(2500 AS BIGINT), N'Phí tạo Competition lớn (tối đa 32 cá nhân hoặc 16 đội)',     CAST(1 AS BIT))
    ) AS source (RuleCode, CreditAmount, Description, IsActive)
    ON target.RuleCode = source.RuleCode
    WHEN MATCHED THEN
        UPDATE SET
            target.CreditAmount = source.CreditAmount,
            target.Description  = source.Description,
            target.IsActive     = source.IsActive,
            target.UpdatedAt    = SYSUTCDATETIME()
    WHEN NOT MATCHED THEN
        INSERT (RuleCode, CreditAmount, Description, IsActive, CreatedAt)
        VALUES (source.RuleCode, source.CreditAmount, source.Description, source.IsActive, SYSUTCDATETIME());

    /* Seed default reward rules ONLY if missing (never overwrite existing reward values) */
    IF NOT EXISTS (SELECT 1 FROM dbo.CreditRules WHERE RuleCode = N'FIRST_LOGIN')
    BEGIN
        INSERT INTO dbo.CreditRules (RuleCode, CreditAmount, Description, IsActive, CreatedAt)
        VALUES (N'FIRST_LOGIN', 200, N'Thưởng Credit lần đăng nhập đầu tiên', 1, SYSUTCDATETIME());
    END;

    IF NOT EXISTS (SELECT 1 FROM dbo.CreditRules WHERE RuleCode = N'DAILY_LOGIN')
    BEGIN
        INSERT INTO dbo.CreditRules (RuleCode, CreditAmount, Description, IsActive, CreatedAt)
        VALUES (N'DAILY_LOGIN', 20, N'Thưởng Credit điểm danh đăng nhập hàng ngày', 1, SYSUTCDATETIME());
    END;

    /* 3. Disable legacy P2P_MATCH_PER_USER rule without deleting historical RewardClaims/logs */
    UPDATE dbo.CreditRules
    SET IsActive = 0,
        Description = N'[DEPRECATED - FREE] Debate P2P hiện miễn phí (0 Credit)',
        UpdatedAt = SYSUTCDATETIME()
    WHERE RuleCode = N'P2P_MATCH_PER_USER';

    /* 4. Ensure schema columns and database-level constraints */
    IF COL_LENGTH('dbo.DebateSessions', 'EnableRag') IS NULL
    BEGIN
        ALTER TABLE dbo.DebateSessions ADD EnableRag BIT NULL CONSTRAINT DF_DebateSessions_EnableRag DEFAULT 1;
    END;

    IF NOT EXISTS (SELECT 1 FROM sys.check_constraints WHERE name = 'CK_Wallets_Balance_NonNegative')
    BEGIN
        ALTER TABLE dbo.Wallets ADD CONSTRAINT CK_Wallets_Balance_NonNegative CHECK ([Balance] >= 0);
    END;

    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF @@TRANCOUNT > 0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;
GO

/* Verification */
SELECT PackageId, PackageCode, PackageName, Price, Currency, CreditAmount, BonusCredit, IsActive
FROM dbo.CreditPackages
ORDER BY Price;

SELECT RuleId, RuleCode, CreditAmount, Description, IsActive
FROM dbo.CreditRules
ORDER BY RuleId;
GO