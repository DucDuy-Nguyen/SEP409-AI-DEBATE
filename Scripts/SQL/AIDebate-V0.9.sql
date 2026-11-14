/* ============================================================
   DEBATE PRACTICE PLATFORM
   SQL SERVER DATABASE
   AIDebate Database Schema Version 0.61
   ============================================================ */

CREATE DATABASE DebatePracticePlatformDB;
GO

USE DebatePracticePlatformDB;
GO

SET ANSI_NULLS ON;
GO
SET QUOTED_IDENTIFIER ON;
GO


/* ============================================================
   01. ROLES
   ============================================================ */

CREATE TABLE Roles (
    RoleId INT IDENTITY(1,1) PRIMARY KEY,
    RoleName NVARCHAR(50) NOT NULL UNIQUE,
    Description NVARCHAR(255) NULL,
    CreatedAt DATETIME2 NOT NULL DEFAULT GETDATE()
);
GO


/* ============================================================
   02. USERS
   ============================================================ */

CREATE TABLE Users (
    UserId INT IDENTITY(1,1) PRIMARY KEY,

    FullName NVARCHAR(150) NOT NULL,
    Email NVARCHAR(255) NOT NULL UNIQUE,
    PasswordHash NVARCHAR(500)  NULL,

    AvatarUrl NVARCHAR(500) NULL,
    DateOfBirth DATE NULL,

    Gender NVARCHAR(20) NULL
        CHECK (Gender IN ('Male', 'Female', 'Other')),

    PhoneNumber NVARCHAR(30) NULL,

    IsEmailVerified BIT NOT NULL DEFAULT 0,
    IsActive BIT NOT NULL DEFAULT 1,

    CreatedAt DATETIME2 NOT NULL DEFAULT GETDATE(),
    UpdatedAt DATETIME2 NULL
);
GO


-- 1. T?o b?ng RefreshTokens
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'RefreshTokens')
BEGIN
    CREATE TABLE [dbo].[RefreshTokens] (
        [Id] INT IDENTITY(1,1) NOT NULL,
        [UserId] INT NOT NULL,
        [Token] NVARCHAR(256) NOT NULL,
        [ExpiresAt] DATETIME2(7) NOT NULL,
        [IsRevoked] BIT NOT NULL CONSTRAINT [DF_RefreshTokens_IsRevoked] DEFAULT (0),
        [CreatedAt] DATETIME2(7) NOT NULL CONSTRAINT [DF_RefreshTokens_CreatedAt] DEFAULT (GETUTCDATE()),
        [ReplacedByToken] NVARCHAR(256) NULL,
        CONSTRAINT [PK_RefreshTokens] PRIMARY KEY CLUSTERED ([Id] ASC),
        CONSTRAINT [FK_RefreshTokens_Users_UserId] FOREIGN KEY ([UserId]) 
            REFERENCES [dbo].[Users] ([UserId]) ON DELETE CASCADE
    );
END
GO
-- 2. T?o Unique Index cho Token ?? tìm ki?m nhanh và ??m b?o duy nh?t
IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'IX_RefreshTokens_Token' AND object_id = OBJECT_ID('[dbo].[RefreshTokens]'))
BEGIN
    CREATE UNIQUE NONCLUSTERED INDEX [IX_RefreshTokens_Token]
    ON [dbo].[RefreshTokens] ([Token] ASC);
END
GO
-- 3. T?o Index cho UserId ?? t?i ?u truy v?n theo User
IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'IX_RefreshTokens_UserId' AND object_id = OBJECT_ID('[dbo].[RefreshTokens]'))
BEGIN
    CREATE NONCLUSTERED INDEX [IX_RefreshTokens_UserId]
    ON [dbo].[RefreshTokens] ([UserId] ASC);
END
GO


/* ============================================================
   03. USER ROLES
   ============================================================ */

CREATE TABLE UserRoles (
    UserId INT NOT NULL,
    RoleId INT NOT NULL,

    AssignedAt DATETIME2 NOT NULL DEFAULT GETDATE(),

    PRIMARY KEY (UserId, RoleId),

    CONSTRAINT FK_UserRoles_Users
        FOREIGN KEY (UserId) REFERENCES Users(UserId),

    CONSTRAINT FK_UserRoles_Roles
        FOREIGN KEY (RoleId) REFERENCES Roles(RoleId)
);
GO


/* ============================================================
   04. TOPICS
   ============================================================ */

CREATE TABLE Topics (
    TopicId INT IDENTITY(1,1) PRIMARY KEY,

    Title NVARCHAR(300) NOT NULL,
    Description NVARCHAR(MAX) NULL,

    Category NVARCHAR(100) NULL,

    Difficulty NVARCHAR(20) NOT NULL DEFAULT 'Medium'
        CHECK (Difficulty IN ('Easy', 'Medium', 'Hard')),

    CreatedBy INT NULL,

    IsActive BIT NOT NULL DEFAULT 1,

    CreatedAt DATETIME2 NOT NULL DEFAULT GETDATE(),
    UpdatedAt DATETIME2 NULL,

    CONSTRAINT FK_Topics_CreatedBy
        FOREIGN KEY (CreatedBy) REFERENCES Users(UserId)
);
GO


/* ============================================================
   05. DEBATE FORMATS
   ============================================================ */

CREATE TABLE DebateFormats (
    FormatId INT IDENTITY(1,1) PRIMARY KEY,

    FormatName NVARCHAR(100) NOT NULL UNIQUE,
    Description NVARCHAR(500) NULL,

    MaxParticipants INT NOT NULL DEFAULT 2
        CHECK (MaxParticipants > 0),

    TotalRounds INT NOT NULL DEFAULT 3
        CHECK (TotalRounds > 0),

    RoundDurationSeconds INT NULL
        CHECK (
            RoundDurationSeconds IS NULL
            OR RoundDurationSeconds > 0
        ),

    IsActive BIT NOT NULL DEFAULT 1,

    CreatedAt DATETIME2 NOT NULL DEFAULT GETDATE()
);
GO


/* ============================================================
   06. DEBATE CRITERIA
   ============================================================ */

CREATE TABLE DebateCriteria (
    CriteriaId INT IDENTITY(1,1) PRIMARY KEY,

    CriteriaName NVARCHAR(100) NOT NULL UNIQUE,
    Description NVARCHAR(500) NULL,

    MaxScore DECIMAL(5,2) NOT NULL DEFAULT 10
        CHECK (MaxScore > 0),

    Weight DECIMAL(5,4) NOT NULL DEFAULT 1
        CHECK (Weight > 0),

    IsActive BIT NOT NULL DEFAULT 1,

    CreatedAt DATETIME2 NOT NULL DEFAULT GETDATE()
);
GO


/* ============================================================
   07. DEBATE SESSIONS
   ============================================================ */

CREATE TABLE DebateSessions (
    DebateSessionId INT IDENTITY(1,1) PRIMARY KEY,

    TopicId INT NOT NULL,
    FormatId INT NOT NULL,
    CreatedBy INT NOT NULL,

    Status NVARCHAR(30) NOT NULL DEFAULT 'Waiting'
        CHECK (
            Status IN (
                'Waiting',
                'InProgress',
                'Completed',
                'Cancelled'
            )
        ),

    StartTime DATETIME2 NULL,
    EndTime DATETIME2 NULL,

    CreatedAt DATETIME2 NOT NULL DEFAULT GETDATE(),
    UpdatedAt DATETIME2 NULL,

    CONSTRAINT FK_DebateSessions_Topics
        FOREIGN KEY (TopicId) REFERENCES Topics(TopicId),

    CONSTRAINT FK_DebateSessions_Formats
        FOREIGN KEY (FormatId) REFERENCES DebateFormats(FormatId),

    CONSTRAINT FK_DebateSessions_CreatedBy
        FOREIGN KEY (CreatedBy) REFERENCES Users(UserId),

    CONSTRAINT CK_DebateSessions_Time
        CHECK (
            EndTime IS NULL
            OR StartTime IS NULL
            OR EndTime >= StartTime
        )
);
GO


/* ============================================================
   08. DEBATE PARTICIPANTS
   ============================================================ */

CREATE TABLE DebateParticipants (
    ParticipantId INT IDENTITY(1,1) PRIMARY KEY,

    DebateSessionId INT NOT NULL,

    UserId INT NULL,

    ParticipantType NVARCHAR(20) NOT NULL
        CHECK (ParticipantType IN ('USER', 'AI')),

    Side NVARCHAR(10) NOT NULL
        CHECK (Side IN ('PRO', 'CON')),

    JoinedAt DATETIME2 NOT NULL DEFAULT GETDATE(),

    CONSTRAINT FK_DebateParticipants_Session
        FOREIGN KEY (DebateSessionId)
        REFERENCES DebateSessions(DebateSessionId),

    CONSTRAINT FK_DebateParticipants_User
        FOREIGN KEY (UserId)
        REFERENCES Users(UserId),

    CONSTRAINT CK_DebateParticipants_Type
        CHECK (
            (ParticipantType = 'USER' AND UserId IS NOT NULL)
            OR
            (ParticipantType = 'AI' AND UserId IS NULL)
        )
);
GO


/* ============================================================
   09. DEBATE ROUNDS
   ============================================================ */

CREATE TABLE DebateRounds (
    RoundId INT IDENTITY(1,1) PRIMARY KEY,

    DebateSessionId INT NOT NULL,

    RoundNumber INT NOT NULL
        CHECK (RoundNumber > 0),

    RoundType NVARCHAR(30) NOT NULL
        CHECK (
            RoundType IN (
                'OPENING',
                'ARGUMENT',
                'REBUTTAL',
                'CLOSING'
            )
        ),

    StartTime DATETIME2 NULL,
    EndTime DATETIME2 NULL,

    CreatedAt DATETIME2 NOT NULL DEFAULT GETDATE(),

    CONSTRAINT FK_DebateRounds_Session
        FOREIGN KEY (DebateSessionId)
        REFERENCES DebateSessions(DebateSessionId),

    CONSTRAINT UQ_DebateRounds
        UNIQUE (DebateSessionId, RoundNumber)
);
GO


/* ============================================================
   10. ARGUMENTS
   ============================================================ */

CREATE TABLE Arguments (
    ArgumentId INT IDENTITY(1,1) PRIMARY KEY,

    RoundId INT NOT NULL,
    ParticipantId INT NOT NULL,

    Content NVARCHAR(MAX) NOT NULL,

    WordCount INT NULL
        CHECK (WordCount IS NULL OR WordCount >= 0),

    DurationSeconds INT NULL
        CHECK (
            DurationSeconds IS NULL
            OR DurationSeconds >= 0
        ),

    SubmittedAt DATETIME2 NOT NULL DEFAULT GETDATE(),

    CONSTRAINT FK_Arguments_Round
        FOREIGN KEY (RoundId)
        REFERENCES DebateRounds(RoundId),

    CONSTRAINT FK_Arguments_Participant
        FOREIGN KEY (ParticipantId)
        REFERENCES DebateParticipants(ParticipantId)
);
GO


/* ============================================================
   11. DEBATE CHALLENGES
   Direct 1v1 challenge before a DebateSession is created
   ============================================================ */

CREATE TABLE DebateChallenges (
    ChallengeId INT IDENTITY(1,1) PRIMARY KEY,

    ChallengerUserId INT NOT NULL,
    ChallengedUserId INT NOT NULL,

    TopicId INT NOT NULL,

    PreferredSide NVARCHAR(10) NOT NULL
        CHECK (PreferredSide IN ('PRO', 'CON')),

    TurnTimeLimitSeconds INT NOT NULL DEFAULT 180
        CHECK (TurnTimeLimitSeconds > 0),

    Status NVARCHAR(20) NOT NULL DEFAULT 'Pending'
        CHECK (
            Status IN (
                'Pending',
                'Accepted',
                'Rejected',
                'Cancelled',
                'Expired'
            )
        ),

    DebateSessionId INT NULL,

    CreatedAt DATETIME2 NOT NULL DEFAULT GETDATE(),
    RespondedAt DATETIME2 NULL,
    ExpiresAt DATETIME2 NULL,

    CONSTRAINT FK_DebateChallenges_Challenger
        FOREIGN KEY (ChallengerUserId)
        REFERENCES Users(UserId),

    CONSTRAINT FK_DebateChallenges_Challenged
        FOREIGN KEY (ChallengedUserId)
        REFERENCES Users(UserId),

    CONSTRAINT FK_DebateChallenges_Topic
        FOREIGN KEY (TopicId)
        REFERENCES Topics(TopicId),

    CONSTRAINT FK_DebateChallenges_DebateSession
        FOREIGN KEY (DebateSessionId)
        REFERENCES DebateSessions(DebateSessionId),

    CONSTRAINT CK_DebateChallenges_DifferentUsers
        CHECK (ChallengerUserId <> ChallengedUserId)
);
GO


/* ============================================================
   11. AI JUDGEMENTS
   ============================================================ */

CREATE TABLE AIJudgements (
    JudgementId INT IDENTITY(1,1) PRIMARY KEY,

    DebateSessionId INT NOT NULL,

    WinnerParticipantId INT NULL,

    SuggestedWinnerSide NVARCHAR(10) NULL,
    OverallScorePro DECIMAL(6,2) NULL,
    OverallScoreCon DECIMAL(6,2) NULL,

    OverallScore DECIMAL(6,2) NULL
        CHECK (
            OverallScore IS NULL
            OR OverallScore >= 0
        ),

    ConfidenceScore DECIMAL(5,4) NULL,
    RawResponseJson NVARCHAR(MAX) NULL,

    OverallFeedback NVARCHAR(MAX) NULL,
    Summary NVARCHAR(MAX) NULL,

    AIProvider NVARCHAR(100) NULL,
    AIModel NVARCHAR(150) NULL,

    CreatedAt DATETIME2 NOT NULL DEFAULT GETDATE(),

    CONSTRAINT FK_AIJudgements_Session
        FOREIGN KEY (DebateSessionId)
        REFERENCES DebateSessions(DebateSessionId),

    CONSTRAINT FK_AIJudgements_Winner
        FOREIGN KEY (WinnerParticipantId)
        REFERENCES DebateParticipants(ParticipantId)
);
GO


/* ============================================================
   12. ARGUMENT SCORES
   ============================================================ */

CREATE TABLE ArgumentScores (
    ArgumentScoreId INT IDENTITY(1,1) PRIMARY KEY,

    ArgumentId INT NOT NULL,
    CriteriaId INT NOT NULL,

    Score DECIMAL(5,2) NOT NULL
        CHECK (Score >= 0),

    Feedback NVARCHAR(MAX) NULL,

    CreatedAt DATETIME2 NOT NULL DEFAULT GETDATE(),

    CONSTRAINT FK_ArgumentScores_Argument
        FOREIGN KEY (ArgumentId)
        REFERENCES Arguments(ArgumentId),

    CONSTRAINT FK_ArgumentScores_Criteria
        FOREIGN KEY (CriteriaId)
        REFERENCES DebateCriteria(CriteriaId),

    CONSTRAINT UQ_ArgumentScores
        UNIQUE (ArgumentId, CriteriaId)
);
GO


/* ============================================================
   13. AI FEATURES
   ============================================================ */

CREATE TABLE AIFeatures (
    FeatureId INT IDENTITY(1,1) PRIMARY KEY,

    FeatureCode NVARCHAR(100) NOT NULL UNIQUE,
    FeatureName NVARCHAR(150) NOT NULL,

    Description NVARCHAR(500) NULL,

    CreditCost INT NOT NULL DEFAULT 0
        CHECK (CreditCost >= 0),

    DailyFreeLimit INT NOT NULL DEFAULT 0
        CHECK (DailyFreeLimit >= 0),

    IsPremiumOnly BIT NOT NULL DEFAULT 0,
    IsActive BIT NOT NULL DEFAULT 1,

    CreatedAt DATETIME2 NOT NULL DEFAULT GETDATE(),
    UpdatedAt DATETIME2 NULL
);
GO


/* ============================================================
   14. AI MODEL CONFIGS
   ============================================================ */

CREATE TABLE AIModelConfigs (
    AIConfigId INT IDENTITY(1,1) PRIMARY KEY,

    FeatureId INT NOT NULL,

    Provider NVARCHAR(100) NOT NULL,
    ModelName NVARCHAR(150) NOT NULL,

    Temperature DECIMAL(4,2) NULL
        CHECK (
            Temperature IS NULL
            OR Temperature BETWEEN 0 AND 2
        ),

    MaxTokens INT NULL
        CHECK (
            MaxTokens IS NULL
            OR MaxTokens > 0
        ),

    IsActive BIT NOT NULL DEFAULT 1,

    CreatedAt DATETIME2 NOT NULL DEFAULT GETDATE(),
    UpdatedAt DATETIME2 NULL,

    CONSTRAINT FK_AIModelConfigs_Feature
        FOREIGN KEY (FeatureId)
        REFERENCES AIFeatures(FeatureId)
);
GO


/* ============================================================
   15. AI HINTS
   ============================================================ */

CREATE TABLE AIHints (
    HintId BIGINT IDENTITY(1,1) PRIMARY KEY,

    UserId INT NOT NULL,
    DebateSessionId INT NOT NULL,
    RoundId INT NULL,

    UserInput NVARCHAR(MAX) NULL,
    HintContent NVARCHAR(MAX) NOT NULL,

    CreditsUsed INT NOT NULL DEFAULT 0
        CHECK (CreditsUsed >= 0),

    AIProvider NVARCHAR(100) NULL,
    AIModel NVARCHAR(150) NULL,

    CreatedAt DATETIME2 NOT NULL DEFAULT GETDATE(),

    CONSTRAINT FK_AIHints_User
        FOREIGN KEY (UserId)
        REFERENCES Users(UserId),

    CONSTRAINT FK_AIHints_Session
        FOREIGN KEY (DebateSessionId)
        REFERENCES DebateSessions(DebateSessionId),

    CONSTRAINT FK_AIHints_Round
        FOREIGN KEY (RoundId)
        REFERENCES DebateRounds(RoundId)
);
GO


/* ============================================================
   16. AI USAGE LOGS
   ============================================================ */

CREATE TABLE AIUsageLogs (
    UsageId BIGINT IDENTITY(1,1) PRIMARY KEY,

    UserId INT NOT NULL,
    FeatureId INT NOT NULL,

    DebateSessionId INT NULL,

    InputTokens INT NOT NULL DEFAULT 0
        CHECK (InputTokens >= 0),

    OutputTokens INT NOT NULL DEFAULT 0
        CHECK (OutputTokens >= 0),

    CreditsUsed INT NOT NULL DEFAULT 0
        CHECK (CreditsUsed >= 0),

    EstimatedCost DECIMAL(18,6) NULL
        CHECK (
            EstimatedCost IS NULL
            OR EstimatedCost >= 0
        ),

    AIProvider NVARCHAR(100) NULL,
    AIModel NVARCHAR(150) NULL,

    CreatedAt DATETIME2 NOT NULL DEFAULT GETDATE(),

    CONSTRAINT FK_AIUsageLogs_User
        FOREIGN KEY (UserId)
        REFERENCES Users(UserId),

    CONSTRAINT FK_AIUsageLogs_Feature
        FOREIGN KEY (FeatureId)
        REFERENCES AIFeatures(FeatureId),

    CONSTRAINT FK_AIUsageLogs_Session
        FOREIGN KEY (DebateSessionId)
        REFERENCES DebateSessions(DebateSessionId)
);
GO


/* ============================================================
   VERSION 0.5 - WALLET / CREDIT / PAYMENT MODULE
   Changes introduced in V0.5:
   - Redefine Wallets
   - Redefine WalletTransactions
   - Add CreditPackages
   - Redefine PaymentTransactions for PayOS top-up
   - Add CreditRules
   - Add RewardClaims
   ============================================================ */


/* V0.5 - REDEFINED: Wallets */
CREATE TABLE Wallets (
    WalletId INT IDENTITY(1,1) PRIMARY KEY,

    UserId INT NOT NULL UNIQUE,

    Balance BIGINT NOT NULL DEFAULT 0
        CHECK (Balance >= 0),

    CreatedAt DATETIME2 NOT NULL DEFAULT GETDATE(),
    UpdatedAt DATETIME2 NULL,

    CONSTRAINT FK_Wallets_User
        FOREIGN KEY (UserId) REFERENCES Users(UserId)
);
GO


/* V0.5 - REDEFINED: WalletTransactions */
CREATE TABLE WalletTransactions (
    WalletTransactionId BIGINT IDENTITY(1,1) PRIMARY KEY,

    WalletId INT NOT NULL,

    TransactionType NVARCHAR(20) NOT NULL
        CHECK (
            TransactionType IN (
                'Credit',
                'Debit'
            )
        ),

    SourceType NVARCHAR(50) NOT NULL
        CHECK (
            SourceType IN (
                'TopUp',
                'Reward',
                'AiUsage',
                'Refund',
                'AdminAdjustment'
            )
        ),

    Amount BIGINT NOT NULL
        CHECK (Amount > 0),

    BalanceBefore BIGINT NOT NULL
        CHECK (BalanceBefore >= 0),

    BalanceAfter BIGINT NOT NULL
        CHECK (BalanceAfter >= 0),

    ReferenceType NVARCHAR(50) NULL,
    ReferenceId BIGINT NULL,

    Description NVARCHAR(500) NULL,

    CreatedAt DATETIME2 NOT NULL DEFAULT GETDATE(),

    CONSTRAINT FK_WalletTransactions_Wallet
        FOREIGN KEY (WalletId) REFERENCES Wallets(WalletId),

    CONSTRAINT CK_WalletTransactions_BalanceMath
        CHECK (
            (TransactionType = 'Credit'
                AND BalanceAfter = BalanceBefore + Amount)
            OR
            (TransactionType = 'Debit'
                AND BalanceAfter = BalanceBefore - Amount)
        )
);
GO


/* V0.5 - NEW: CreditPackages */
CREATE TABLE CreditPackages (
    PackageId INT IDENTITY(1,1) PRIMARY KEY,

    PackageCode NVARCHAR(50) NOT NULL UNIQUE,
    PackageName NVARCHAR(100) NOT NULL,

    Price DECIMAL(18,2) NOT NULL
        CHECK (Price > 0),

    Currency NVARCHAR(10) NOT NULL DEFAULT 'VND',

    CreditAmount BIGINT NOT NULL
        CHECK (CreditAmount > 0),

    BonusCredit BIGINT NOT NULL DEFAULT 0
        CHECK (BonusCredit >= 0),

    IsActive BIT NOT NULL DEFAULT 1,

    CreatedAt DATETIME2 NOT NULL DEFAULT GETDATE(),
    UpdatedAt DATETIME2 NULL
);
GO


/* V0.5 - REDEFINED: PaymentTransactions */
CREATE TABLE PaymentTransactions (
    PaymentId BIGINT IDENTITY(1,1) PRIMARY KEY,

    UserId INT NOT NULL,
    WalletId INT NOT NULL,
    PackageId INT NOT NULL,

    Amount DECIMAL(18,2) NOT NULL
        CHECK (Amount > 0),

    Currency NVARCHAR(10) NOT NULL DEFAULT 'VND',

    CreditAmount BIGINT NOT NULL
        CHECK (CreditAmount > 0),

    Provider NVARCHAR(50) NOT NULL DEFAULT 'PayOS',

    ProviderOrderCode BIGINT NOT NULL,

    ProviderTransactionId NVARCHAR(255) NULL,

    Status NVARCHAR(30) NOT NULL DEFAULT 'Pending'
        CHECK (
            Status IN (
                'Pending',
                'Paid',
                'Failed',
                'Cancelled',
                'Expired'
            )
        ),

    CreatedAt DATETIME2 NOT NULL DEFAULT GETDATE(),
    PaidAt DATETIME2 NULL,
    CancelledAt DATETIME2 NULL,
    ExpiredAt DATETIME2 NULL,

    CONSTRAINT FK_PaymentTransactions_User
        FOREIGN KEY (UserId) REFERENCES Users(UserId),

    CONSTRAINT FK_PaymentTransactions_Wallet
        FOREIGN KEY (WalletId) REFERENCES Wallets(WalletId),

    CONSTRAINT FK_PaymentTransactions_Package
        FOREIGN KEY (PackageId) REFERENCES CreditPackages(PackageId),

    CONSTRAINT UQ_PaymentTransactions_Provider_OrderCode
        UNIQUE (Provider, ProviderOrderCode)
);
GO


/* V0.5 - NEW: CreditRules */
CREATE TABLE CreditRules (
    RuleId INT IDENTITY(1,1) PRIMARY KEY,

    RuleCode NVARCHAR(50) NOT NULL UNIQUE,

    CreditAmount BIGINT NOT NULL
        CHECK (CreditAmount > 0),

    Description NVARCHAR(255) NULL,

    IsActive BIT NOT NULL DEFAULT 1,

    CreatedAt DATETIME2 NOT NULL DEFAULT GETDATE(),
    UpdatedAt DATETIME2 NULL
);
GO


/* V0.5 - NEW: RewardClaims */
CREATE TABLE RewardClaims (
    RewardClaimId BIGINT IDENTITY(1,1) PRIMARY KEY,

    UserId INT NOT NULL,
    RuleId INT NOT NULL,

    ClaimKey NVARCHAR(50) NOT NULL,

    ClaimedAt DATETIME2 NOT NULL DEFAULT GETDATE(),

    ReferenceId BIGINT NULL,

    CONSTRAINT FK_RewardClaims_User
        FOREIGN KEY (UserId) REFERENCES Users(UserId),

    CONSTRAINT FK_RewardClaims_Rule
        FOREIGN KEY (RuleId) REFERENCES CreditRules(RuleId),

    CONSTRAINT UQ_RewardClaims_User_Rule_ClaimKey
        UNIQUE (UserId, RuleId, ClaimKey)
);
GO


/* ============================================================
   20. SUBSCRIPTION PLANS
   ============================================================ */

CREATE TABLE SubscriptionPlans (
    PlanId INT IDENTITY(1,1) PRIMARY KEY,

    PlanCode NVARCHAR(50) NOT NULL UNIQUE,
    PlanName NVARCHAR(100) NOT NULL,

    Description NVARCHAR(500) NULL,

    Price DECIMAL(18,2) NOT NULL DEFAULT 0
        CHECK (Price >= 0),

    DurationDays INT NOT NULL
        CHECK (DurationDays > 0),

    MonthlyCredits INT NOT NULL DEFAULT 0
        CHECK (MonthlyCredits >= 0),

    IsActive BIT NOT NULL DEFAULT 1,

    CreatedAt DATETIME2 NOT NULL DEFAULT GETDATE(),
    UpdatedAt DATETIME2 NULL
);
GO


/* ============================================================
   21. PLAN BENEFITS
   ============================================================ */

CREATE TABLE PlanBenefits (
    PlanBenefitId INT IDENTITY(1,1) PRIMARY KEY,

    PlanId INT NOT NULL,
    FeatureId INT NOT NULL,

    UsageLimit INT NULL
        CHECK (
            UsageLimit IS NULL
            OR UsageLimit >= 0
        ),

    IsUnlimited BIT NOT NULL DEFAULT 0,

    CreatedAt DATETIME2 NOT NULL DEFAULT GETDATE(),

    CONSTRAINT FK_PlanBenefits_Plan
        FOREIGN KEY (PlanId)
        REFERENCES SubscriptionPlans(PlanId),

    CONSTRAINT FK_PlanBenefits_Feature
        FOREIGN KEY (FeatureId)
        REFERENCES AIFeatures(FeatureId),

    CONSTRAINT UQ_PlanBenefits
        UNIQUE (PlanId, FeatureId)
);
GO


/* ============================================================
   22. USER SUBSCRIPTIONS
   ============================================================ */

CREATE TABLE UserSubscriptions (
    UserSubscriptionId BIGINT IDENTITY(1,1) PRIMARY KEY,

    UserId INT NOT NULL,
    PlanId INT NOT NULL,

    PaymentId BIGINT NULL,

    StartDate DATETIME2 NOT NULL,
    EndDate DATETIME2 NOT NULL,

    Status NVARCHAR(30) NOT NULL DEFAULT 'Active'
        CHECK (
            Status IN (
                'Pending',
                'Active',
                'Expired',
                'Cancelled'
            )
        ),

    AutoRenew BIT NOT NULL DEFAULT 0,

    CreatedAt DATETIME2 NOT NULL DEFAULT GETDATE(),
    UpdatedAt DATETIME2 NULL,

    CONSTRAINT FK_UserSubscriptions_User
        FOREIGN KEY (UserId)
        REFERENCES Users(UserId),

    CONSTRAINT FK_UserSubscriptions_Plan
        FOREIGN KEY (PlanId)
        REFERENCES SubscriptionPlans(PlanId),

    CONSTRAINT FK_UserSubscriptions_Payment
        FOREIGN KEY (PaymentId)
        REFERENCES PaymentTransactions(PaymentId),

    CONSTRAINT CK_UserSubscriptions_Dates
        CHECK (EndDate > StartDate)
);
GO


/* ============================================================
   23. USER STATISTICS
   ============================================================ */

CREATE TABLE UserStatistics (
    UserStatisticId INT IDENTITY(1,1) PRIMARY KEY,

    UserId INT NOT NULL UNIQUE,

    TotalDebates INT NOT NULL DEFAULT 0,
    TotalWins INT NOT NULL DEFAULT 0,
    TotalLosses INT NOT NULL DEFAULT 0,
    TotalDraws INT NOT NULL DEFAULT 0,

    AverageScore DECIMAL(6,2) NOT NULL DEFAULT 0,

    CurrentWinStreak INT NOT NULL DEFAULT 0,
    HighestWinStreak INT NOT NULL DEFAULT 0,

    UpdatedAt DATETIME2 NOT NULL DEFAULT GETDATE(),

    CONSTRAINT FK_UserStatistics_User
        FOREIGN KEY (UserId)
        REFERENCES Users(UserId),

    CONSTRAINT CK_UserStatistics
        CHECK (
            TotalDebates >= 0
            AND TotalWins >= 0
            AND TotalLosses >= 0
            AND TotalDraws >= 0
            AND AverageScore >= 0
            AND CurrentWinStreak >= 0
            AND HighestWinStreak >= 0
        )
);
GO


/* ============================================================
   24. SKILL STATISTICS
   ============================================================ */

CREATE TABLE SkillStatistics (
    SkillStatisticId INT IDENTITY(1,1) PRIMARY KEY,

    UserId INT NOT NULL,
    CriteriaId INT NOT NULL,

    AverageScore DECIMAL(6,2) NOT NULL DEFAULT 0,
    HighestScore DECIMAL(6,2) NOT NULL DEFAULT 0,

    TotalAttempts INT NOT NULL DEFAULT 0,

    UpdatedAt DATETIME2 NOT NULL DEFAULT GETDATE(),

    CONSTRAINT FK_SkillStatistics_User
        FOREIGN KEY (UserId)
        REFERENCES Users(UserId),

    CONSTRAINT FK_SkillStatistics_Criteria
        FOREIGN KEY (CriteriaId)
        REFERENCES DebateCriteria(CriteriaId),

    CONSTRAINT UQ_SkillStatistics
        UNIQUE (UserId, CriteriaId),

    CONSTRAINT CK_SkillStatistics
        CHECK (
            AverageScore >= 0
            AND HighestScore >= 0
            AND TotalAttempts >= 0
        )
);
GO


/* ============================================================
   25. ACHIEVEMENTS
   ============================================================ */

CREATE TABLE Achievements (
    AchievementId INT IDENTITY(1,1) PRIMARY KEY,

    AchievementCode NVARCHAR(100) NOT NULL UNIQUE,

    Name NVARCHAR(150) NOT NULL,
    Description NVARCHAR(500) NULL,

    IconUrl NVARCHAR(500) NULL,

    ConditionType NVARCHAR(100) NULL,
    ConditionValue INT NULL,

    IsActive BIT NOT NULL DEFAULT 1,

    CreatedAt DATETIME2 NOT NULL DEFAULT GETDATE()
);
GO


/* ============================================================
   26. USER ACHIEVEMENTS
   ============================================================ */

CREATE TABLE UserAchievements (
    UserAchievementId BIGINT IDENTITY(1,1) PRIMARY KEY,

    UserId INT NOT NULL,
    AchievementId INT NOT NULL,

    UnlockedAt DATETIME2 NOT NULL DEFAULT GETDATE(),

    CONSTRAINT FK_UserAchievements_User
        FOREIGN KEY (UserId)
        REFERENCES Users(UserId),

    CONSTRAINT FK_UserAchievements_Achievement
        FOREIGN KEY (AchievementId)
        REFERENCES Achievements(AchievementId),

    CONSTRAINT UQ_UserAchievements
        UNIQUE (UserId, AchievementId)
);
GO


/* ============================================================
   27. REPORTS
   ============================================================ */

CREATE TABLE Reports (
    ReportId BIGINT IDENTITY(1,1) PRIMARY KEY,

    ReportedBy INT NOT NULL,

    TargetType NVARCHAR(50) NOT NULL
        CHECK (
            TargetType IN (
                'USER',
                'ARGUMENT',
                'TOPIC'
            )
        ),

    TargetId BIGINT NOT NULL,

    Reason NVARCHAR(255) NOT NULL,
    Description NVARCHAR(MAX) NULL,

    Status NVARCHAR(30) NOT NULL DEFAULT 'Pending'
        CHECK (
            Status IN (
                'Pending',
                'Reviewed',
                'Rejected',
                'Resolved'
            )
        ),

    ReviewedBy INT NULL,
    ReviewNote NVARCHAR(MAX) NULL,

    CreatedAt DATETIME2 NOT NULL DEFAULT GETDATE(),
    ReviewedAt DATETIME2 NULL,

    CONSTRAINT FK_Reports_ReportedBy
        FOREIGN KEY (ReportedBy)
        REFERENCES Users(UserId),

    CONSTRAINT FK_Reports_ReviewedBy
        FOREIGN KEY (ReviewedBy)
        REFERENCES Users(UserId)
);
GO


/* ============================================================
   28. NOTIFICATIONS
   ============================================================ */

CREATE TABLE Notifications (
    NotificationId BIGINT IDENTITY(1,1) PRIMARY KEY,

    UserId INT NOT NULL,

    Title NVARCHAR(255) NOT NULL,
    Content NVARCHAR(MAX) NOT NULL,

    Type NVARCHAR(100) NULL,

    IsRead BIT NOT NULL DEFAULT 0,

    ReferenceType NVARCHAR(100) NULL,
    ReferenceId BIGINT NULL,

    CreatedAt DATETIME2 NOT NULL DEFAULT GETDATE(),
    ReadAt DATETIME2 NULL,

    CONSTRAINT FK_Notifications_User
        FOREIGN KEY (UserId)
        REFERENCES Users(UserId)
);
GO


/* ============================================================
   29. COMPETITIONS
   Lecturer/Admin creates competitions
   ============================================================ */

CREATE TABLE Competitions (
    CompetitionId INT IDENTITY(1,1) PRIMARY KEY,

    Title NVARCHAR(200) NOT NULL,
    Description NVARCHAR(MAX) NULL,

    CreatedBy INT NOT NULL,

    CompetitionType NVARCHAR(30) NOT NULL
        CHECK (
            CompetitionType IN (
                'INDIVIDUAL',
                'TEAM'
            )
        ),

    FormatId INT NULL,

    MaxParticipants INT NULL
        CHECK (
            MaxParticipants IS NULL
            OR MaxParticipants > 0
        ),

    RegistrationStart DATETIME2 NOT NULL,
    RegistrationEnd DATETIME2 NOT NULL,

    StartDate DATETIME2 NOT NULL,
    EndDate DATETIME2 NULL,

    Status NVARCHAR(30) NOT NULL DEFAULT 'Draft'
        CHECK (
            Status IN (
                'Draft',
                'OpenRegistration',
                'RegistrationClosed',
                'Ongoing',
                'Completed',
                'Cancelled'
            )
        ),

    IsPublic BIT NOT NULL DEFAULT 1,

    CreatedAt DATETIME2 NOT NULL DEFAULT GETDATE(),
    UpdatedAt DATETIME2 NULL,

    CONSTRAINT FK_Competitions_CreatedBy
        FOREIGN KEY (CreatedBy)
        REFERENCES Users(UserId),

    CONSTRAINT FK_Competitions_Format
        FOREIGN KEY (FormatId)
        REFERENCES DebateFormats(FormatId),

    CONSTRAINT CK_Competitions_Registration
        CHECK (
            RegistrationEnd > RegistrationStart
        ),

    CONSTRAINT CK_Competitions_StartDate
        CHECK (
            StartDate >= RegistrationEnd
        ),

    CONSTRAINT CK_Competitions_EndDate
        CHECK (
            EndDate IS NULL
            OR EndDate >= StartDate
        )
);
GO


/* ============================================================
   30. COMPETITION REGISTRATIONS
   Individual registration
   ============================================================ */

CREATE TABLE CompetitionRegistrations (
    RegistrationId BIGINT IDENTITY(1,1) PRIMARY KEY,

    CompetitionId INT NOT NULL,
    UserId INT NOT NULL,

    Status NVARCHAR(20) NOT NULL DEFAULT 'Pending'
        CHECK (
            Status IN (
                'Pending',
                'Approved',
                'Rejected',
                'Cancelled'
            )
        ),

    Note NVARCHAR(500) NULL,

    RegisteredAt DATETIME2 NOT NULL DEFAULT GETDATE(),

    ReviewedBy INT NULL,
    ReviewedAt DATETIME2 NULL,

    CONSTRAINT FK_CompetitionRegistrations_Competition
        FOREIGN KEY (CompetitionId)
        REFERENCES Competitions(CompetitionId),

    CONSTRAINT FK_CompetitionRegistrations_User
        FOREIGN KEY (UserId)
        REFERENCES Users(UserId),

    CONSTRAINT FK_CompetitionRegistrations_ReviewedBy
        FOREIGN KEY (ReviewedBy)
        REFERENCES Users(UserId),

    CONSTRAINT UQ_CompetitionRegistrations
        UNIQUE (CompetitionId, UserId)
);
GO


/* ============================================================
   31. COMPETITION TEAMS
   ============================================================ */

CREATE TABLE CompetitionTeams (
    TeamId INT IDENTITY(1,1) PRIMARY KEY,

    CompetitionId INT NOT NULL,

    TeamName NVARCHAR(150) NOT NULL,

    CaptainUserId INT NOT NULL,

    Status NVARCHAR(20) NOT NULL DEFAULT 'Active'
        CHECK (
            Status IN (
                'Active',
                'Eliminated',
                'Withdrawn',
                'Disqualified'
            )
        ),

    CreatedAt DATETIME2 NOT NULL DEFAULT GETDATE(),

    CONSTRAINT FK_CompetitionTeams_Competition
        FOREIGN KEY (CompetitionId)
        REFERENCES Competitions(CompetitionId),

    CONSTRAINT FK_CompetitionTeams_Captain
        FOREIGN KEY (CaptainUserId)
        REFERENCES Users(UserId),

    CONSTRAINT UQ_CompetitionTeams_Name
        UNIQUE (CompetitionId, TeamName)
);
GO


/* ============================================================
   32. COMPETITION TEAM MEMBERS
   ============================================================ */

CREATE TABLE CompetitionTeamMembers (
    TeamMemberId BIGINT IDENTITY(1,1) PRIMARY KEY,

    TeamId INT NOT NULL,
    UserId INT NOT NULL,

    JoinedAt DATETIME2 NOT NULL DEFAULT GETDATE(),

    CONSTRAINT FK_CompetitionTeamMembers_Team
        FOREIGN KEY (TeamId)
        REFERENCES CompetitionTeams(TeamId),

    CONSTRAINT FK_CompetitionTeamMembers_User
        FOREIGN KEY (UserId)
        REFERENCES Users(UserId),

    CONSTRAINT UQ_CompetitionTeamMembers
        UNIQUE (TeamId, UserId)
);
GO


/* ============================================================
   33. COMPETITION TEAM REQUESTS
   ============================================================ */

CREATE TABLE dbo.CompetitionTeamRequests (
    RequestId BIGINT IDENTITY(1,1) NOT NULL,

    TeamId INT NOT NULL,
    UserId INT NOT NULL,
    CreatedByUserId INT NOT NULL,

    RequestType NVARCHAR(20) NOT NULL,

    Status NVARCHAR(20) NOT NULL
        CONSTRAINT DF_CompetitionTeamRequests_Status
        DEFAULT 'Pending',

    Note NVARCHAR(500) NULL,

    CreatedAt DATETIME2 NOT NULL
        CONSTRAINT DF_CompetitionTeamRequests_CreatedAt
        DEFAULT GETDATE(),

    RespondedAt DATETIME2 NULL,
    RespondedByUserId INT NULL,

    CONSTRAINT PK_CompetitionTeamRequests
        PRIMARY KEY (RequestId),

    CONSTRAINT CK_CompetitionTeamRequests_RequestType
        CHECK (
            RequestType IN (
                'Invitation',
                'JoinRequest'
            )
        ),

    CONSTRAINT CK_CompetitionTeamRequests_Status
        CHECK (
            Status IN (
                'Pending',
                'Accepted',
                'Rejected',
                'Cancelled'
            )
        ),

    CONSTRAINT FK_CompetitionTeamRequests_Team
        FOREIGN KEY (TeamId)
        REFERENCES dbo.CompetitionTeams(TeamId),

    CONSTRAINT FK_CompetitionTeamRequests_User
        FOREIGN KEY (UserId)
        REFERENCES dbo.Users(UserId),

    CONSTRAINT FK_CompetitionTeamRequests_CreatedBy
        FOREIGN KEY (CreatedByUserId)
        REFERENCES dbo.Users(UserId),

    CONSTRAINT FK_CompetitionTeamRequests_RespondedBy
        FOREIGN KEY (RespondedByUserId)
        REFERENCES dbo.Users(UserId)
);
GO


/* ============================================================
   34. COMPETITION ROUNDS
   ============================================================ */

CREATE TABLE CompetitionRounds (
    CompetitionRoundId INT IDENTITY(1,1) PRIMARY KEY,

    CompetitionId INT NOT NULL,

    RoundNumber INT NOT NULL
        CHECK (RoundNumber > 0),

    RoundName NVARCHAR(100) NOT NULL,

    RoundType NVARCHAR(30) NULL
        CHECK (
            RoundType IS NULL
            OR RoundType IN (
                'QUALIFIER',
                'GROUP',
                'ROUND_OF_16',
                'QUARTERFINAL',
                'SEMIFINAL',
                'FINAL'
            )
        ),

    StartDate DATETIME2 NULL,
    EndDate DATETIME2 NULL,

    Status NVARCHAR(20) NOT NULL DEFAULT 'Pending'
        CHECK (
            Status IN (
                'Pending',
                'Ongoing',
                'Completed'
            )
        ),

    CreatedAt DATETIME2 NOT NULL DEFAULT GETDATE(),

    CONSTRAINT FK_CompetitionRounds_Competition
        FOREIGN KEY (CompetitionId)
        REFERENCES Competitions(CompetitionId),

    CONSTRAINT UQ_CompetitionRounds
        UNIQUE (CompetitionId, RoundNumber),

    CONSTRAINT CK_CompetitionRounds_Dates
        CHECK (
            EndDate IS NULL
            OR StartDate IS NULL
            OR EndDate >= StartDate
        )
);
GO


/* ============================================================
   35. COMPETITION JUDGES
   Lecturer / Human judge
   ============================================================ */

CREATE TABLE CompetitionJudges (
    CompetitionJudgeId INT IDENTITY(1,1) PRIMARY KEY,

    CompetitionId INT NOT NULL,
    UserId INT NOT NULL,

    AssignedAt DATETIME2 NOT NULL DEFAULT GETDATE(),

    CONSTRAINT FK_CompetitionJudges_Competition
        FOREIGN KEY (CompetitionId)
        REFERENCES Competitions(CompetitionId),

    CONSTRAINT FK_CompetitionJudges_User
        FOREIGN KEY (UserId)
        REFERENCES Users(UserId),

    CONSTRAINT UQ_CompetitionJudges
        UNIQUE (CompetitionId, UserId)
);
GO


/* ============================================================
   36. COMPETITION MATCHES
   ============================================================ */

CREATE TABLE CompetitionMatches (
    CompetitionMatchId INT IDENTITY(1,1) PRIMARY KEY,

    CompetitionId INT NOT NULL,
    CompetitionRoundId INT NOT NULL,

    DebateSessionId INT NULL,

    MatchNumber INT NOT NULL
        CHECK (MatchNumber > 0),

    BracketPosition INT NOT NULL DEFAULT 1
        CHECK (BracketPosition > 0),

    NextMatchId INT NULL,
    AssignedJudgeUserId INT NULL,

    ScheduledAt DATETIME2 NULL,
    StartedAt DATETIME2 NULL,
    CompletedAt DATETIME2 NULL,

    Status NVARCHAR(30) NOT NULL DEFAULT 'Scheduled'
        CHECK (
            Status IN (
                'Scheduled',
                'Ready',
                'Ongoing',
                'Evaluating',
                'Completed',
                'Cancelled',
                'Bye'
            )
        ),

    WinnerUserId INT NULL,
    WinnerTeamId INT NULL,

    CreatedAt DATETIME2 NOT NULL DEFAULT GETDATE(),
    UpdatedAt DATETIME2 NULL,
    RowVersion ROWVERSION NOT NULL,

    CONSTRAINT FK_CompetitionMatches_Competition
        FOREIGN KEY (CompetitionId)
        REFERENCES Competitions(CompetitionId),

    CONSTRAINT FK_CompetitionMatches_Round
        FOREIGN KEY (CompetitionRoundId)
        REFERENCES CompetitionRounds(CompetitionRoundId),

    CONSTRAINT FK_CompetitionMatches_DebateSession
        FOREIGN KEY (DebateSessionId)
        REFERENCES DebateSessions(DebateSessionId),

    CONSTRAINT FK_CompetitionMatches_NextMatch
        FOREIGN KEY (NextMatchId)
        REFERENCES CompetitionMatches(CompetitionMatchId),

    CONSTRAINT FK_CompetitionMatches_AssignedJudge
        FOREIGN KEY (AssignedJudgeUserId)
        REFERENCES Users(UserId),

    CONSTRAINT FK_CompetitionMatches_WinnerUser
        FOREIGN KEY (WinnerUserId)
        REFERENCES Users(UserId),

    CONSTRAINT FK_CompetitionMatches_WinnerTeam
        FOREIGN KEY (WinnerTeamId)
        REFERENCES CompetitionTeams(TeamId),

    CONSTRAINT UQ_CompetitionMatches
        UNIQUE (CompetitionRoundId, MatchNumber),

    CONSTRAINT UQ_CompetitionMatches_Round_Position
        UNIQUE (CompetitionRoundId, BracketPosition),

    CONSTRAINT CK_CompetitionMatches_Winner
        CHECK (
            NOT (
                WinnerUserId IS NOT NULL
                AND WinnerTeamId IS NOT NULL
            )
        )
);
GO


/* ============================================================
   37. MATCH PARTICIPANTS
   Supports individual AND team tournaments
   ============================================================ */

CREATE TABLE MatchParticipants (
    MatchParticipantId BIGINT IDENTITY(1,1) PRIMARY KEY,

    CompetitionMatchId INT NOT NULL,

    UserId INT NULL,
    TeamId INT NULL,

    Side NVARCHAR(10) NOT NULL
        CHECK (
            Side IN ('PRO', 'CON')
        ),

    SeedNumber INT NULL
        CHECK (
            SeedNumber IS NULL
            OR SeedNumber > 0
        ),

    FinalScore DECIMAL(5,2) NULL
        CHECK (
            FinalScore IS NULL
            OR FinalScore >= 0
        ),

    IsWinner BIT NOT NULL DEFAULT 0,

    CreatedAt DATETIME2 NOT NULL DEFAULT GETDATE(),

    CONSTRAINT FK_MatchParticipants_Match
        FOREIGN KEY (CompetitionMatchId)
        REFERENCES CompetitionMatches(CompetitionMatchId),

    CONSTRAINT FK_MatchParticipants_User
        FOREIGN KEY (UserId)
        REFERENCES Users(UserId),

    CONSTRAINT FK_MatchParticipants_Team
        FOREIGN KEY (TeamId)
        REFERENCES CompetitionTeams(TeamId),

    CONSTRAINT CK_MatchParticipants_Type
        CHECK (
            (UserId IS NOT NULL AND TeamId IS NULL)
            OR
            (UserId IS NULL AND TeamId IS NOT NULL)
        ),

    CONSTRAINT UQ_MatchParticipants_Side
        UNIQUE (CompetitionMatchId, Side)
);
GO


/* ============================================================
   38. JUDGE SCORES
   Human judge scoring
   ============================================================ */

CREATE TABLE JudgeScores (
    JudgeScoreId BIGINT IDENTITY(1,1) PRIMARY KEY,

    CompetitionMatchId INT NOT NULL,

    JudgeUserId INT NOT NULL,

    MatchParticipantId BIGINT NOT NULL,

    CriteriaId INT NOT NULL,

    Score DECIMAL(5,2) NOT NULL
        CHECK (Score >= 0),

    Feedback NVARCHAR(MAX) NULL,

    CreatedAt DATETIME2 NOT NULL DEFAULT GETDATE(),

    CONSTRAINT FK_JudgeScores_Match
        FOREIGN KEY (CompetitionMatchId)
        REFERENCES CompetitionMatches(CompetitionMatchId),

    CONSTRAINT FK_JudgeScores_Judge
        FOREIGN KEY (JudgeUserId)
        REFERENCES Users(UserId),

    CONSTRAINT FK_JudgeScores_Participant
        FOREIGN KEY (MatchParticipantId)
        REFERENCES MatchParticipants(MatchParticipantId),

    CONSTRAINT FK_JudgeScores_Criteria
        FOREIGN KEY (CriteriaId)
        REFERENCES DebateCriteria(CriteriaId),

    CONSTRAINT UQ_JudgeScores
        UNIQUE (
            CompetitionMatchId,
            JudgeUserId,
            MatchParticipantId,
            CriteriaId
        )
);
GO


/* ============================================================
   INDEXES
   ============================================================ */

CREATE INDEX IX_DebateSessions_CreatedBy
ON DebateSessions(CreatedBy);
GO

CREATE INDEX IX_DebateSessions_Status
ON DebateSessions(Status);
GO

CREATE INDEX IX_DebateSessions_Topic
ON DebateSessions(TopicId);
GO

CREATE INDEX IX_DebateParticipants_Session
ON DebateParticipants(DebateSessionId);
GO

CREATE INDEX IX_DebateParticipants_User
ON DebateParticipants(UserId);
GO

CREATE INDEX IX_DebateRounds_Session
ON DebateRounds(DebateSessionId);
GO

CREATE INDEX IX_Arguments_Round
ON Arguments(RoundId);
GO

CREATE INDEX IX_Arguments_Participant
ON Arguments(ParticipantId);
GO


CREATE INDEX IX_DebateChallenges_Challenger
ON DebateChallenges(ChallengerUserId);
GO

CREATE INDEX IX_DebateChallenges_Challenged
ON DebateChallenges(ChallengedUserId);
GO

CREATE INDEX IX_DebateChallenges_Status
ON DebateChallenges(Status);
GO

CREATE INDEX IX_DebateChallenges_Topic
ON DebateChallenges(TopicId);
GO

CREATE INDEX IX_DebateChallenges_DebateSession
ON DebateChallenges(DebateSessionId);
GO

CREATE INDEX IX_DebateChallenges_CreatedAt
ON DebateChallenges(CreatedAt);
GO

CREATE UNIQUE INDEX UQ_DebateChallenges_Pending
ON DebateChallenges(ChallengerUserId, ChallengedUserId)
WHERE Status = 'Pending';
GO


CREATE INDEX IX_AIHints_User
ON AIHints(UserId);
GO

CREATE INDEX IX_AIHints_Session
ON AIHints(DebateSessionId);
GO

CREATE INDEX IX_AIUsageLogs_User
ON AIUsageLogs(UserId);
GO

CREATE INDEX IX_AIUsageLogs_Feature
ON AIUsageLogs(FeatureId);
GO

CREATE INDEX IX_AIUsageLogs_CreatedAt
ON AIUsageLogs(CreatedAt);
GO

CREATE INDEX IX_WalletTransactions_Wallet
ON WalletTransactions(WalletId);
GO

CREATE INDEX IX_WalletTransactions_CreatedAt
ON WalletTransactions(CreatedAt);
GO

CREATE INDEX IX_WalletTransactions_Reference
ON WalletTransactions(ReferenceType, ReferenceId);
GO

CREATE INDEX IX_CreditPackages_IsActive
ON CreditPackages(IsActive);
GO

CREATE INDEX IX_PaymentTransactions_User
ON PaymentTransactions(UserId);
GO

CREATE INDEX IX_PaymentTransactions_Wallet
ON PaymentTransactions(WalletId);
GO

CREATE INDEX IX_PaymentTransactions_Status
ON PaymentTransactions(Status);
GO

CREATE INDEX IX_CreditRules_IsActive
ON CreditRules(IsActive);
GO

CREATE INDEX IX_RewardClaims_User
ON RewardClaims(UserId);
GO

CREATE INDEX IX_RewardClaims_Rule
ON RewardClaims(RuleId);
GO

CREATE INDEX IX_UserSubscriptions_User
ON UserSubscriptions(UserId);
GO

CREATE INDEX IX_UserSubscriptions_Status
ON UserSubscriptions(Status);
GO

CREATE INDEX IX_Notifications_User_IsRead
ON Notifications(UserId, IsRead);
GO

CREATE INDEX IX_Competitions_CreatedBy
ON Competitions(CreatedBy);
GO

CREATE INDEX IX_Competitions_Status
ON Competitions(Status);
GO

CREATE INDEX IX_CompetitionRegistrations_Competition
ON CompetitionRegistrations(CompetitionId);
GO

CREATE INDEX IX_CompetitionTeams_Competition
ON CompetitionTeams(CompetitionId);
GO

CREATE UNIQUE INDEX UQ_CompetitionTeamRequests_Pending
ON dbo.CompetitionTeamRequests(TeamId, UserId)
WHERE Status = 'Pending';
GO

CREATE INDEX IX_CompetitionTeamRequests_Team_Status
ON dbo.CompetitionTeamRequests(TeamId, Status);
GO

CREATE INDEX IX_CompetitionTeamRequests_User_Status
ON dbo.CompetitionTeamRequests(UserId, Status);
GO

CREATE INDEX IX_CompetitionRounds_Competition
ON CompetitionRounds(CompetitionId);
GO

CREATE INDEX IX_CompetitionMatches_Competition
ON CompetitionMatches(CompetitionId);
GO

CREATE INDEX IX_CompetitionMatches_Round
ON CompetitionMatches(CompetitionRoundId);
GO

CREATE INDEX IX_MatchParticipants_Match
ON MatchParticipants(CompetitionMatchId);
GO

CREATE INDEX IX_JudgeScores_Match
ON JudgeScores(CompetitionMatchId);
GO


/* ============================================================
   DEFAULT ROLES
   ============================================================ */

INSERT INTO Roles (RoleName, Description)
VALUES
('Admin', 'System administrator'),
('Lecturer', 'Lecturer who can organize and manage competitions'),
('Member', 'Normal platform member / student'),
('Moderator', 'Platform content moderator');
GO


/* ============================================================
   DEFAULT DEBATE FORMATS
   ============================================================ */

INSERT INTO DebateFormats
(
    FormatName,
    Description,
    MaxParticipants,
    TotalRounds,
    RoundDurationSeconds
)
VALUES
(
    'User vs AI',
    'A user debates against an AI opponent',
    2,
    3,
    180
),
(
    '1 vs 1',
    'Two users debate against each other',
    2,
    3,
    180
),
(
    'Solo Practice',
    'Individual debate practice',
    1,
    3,
    180
),
(
    'Team Debate',
    'Two teams debate against each other',
    6,
    3,
    300
);
GO


/* ============================================================
   DEFAULT DEBATE CRITERIA
   ============================================================ */

INSERT INTO DebateCriteria
(
    CriteriaName,
    Description,
    MaxScore,
    Weight
)
VALUES
(
    'Logic',
    'Logical consistency, reasoning validity, and avoidance of fallacies',
    20.00,
    1.0000
),
(
    'Evidence',
    'Quality, relevance, and credibility of supporting facts and examples',
    20.00,
    1.0000
),
(
    'Relevance',
    'Direct address of the core motion and debate clash points',
    20.00,
    1.0000
),
(
    'Structure',
    'Clarity, organizational flow, transitions, and time management',
    20.00,
    1.0000
),
(
    'Persuasiveness',
    'Rhetorical effectiveness, convincing impact, and audience conviction',
    20.00,
    1.0000
);
GO


/* ============================================================
   DEFAULT AI FEATURES
   ============================================================ */

INSERT INTO AIFeatures
(
    FeatureCode,
    FeatureName,
    Description,
    CreditCost,
    DailyFreeLimit,
    IsPremiumOnly
)
VALUES
(
    'AI_HINT',
    'AI Debate Hint',
    'AI suggests ideas during a debate',
    10,
    3,
    0
),
(
    'ARGUMENT_ANALYSIS',
    'Argument Analysis',
    'AI analyzes strengths and weaknesses of an argument',
    15,
    1,
    0
),
(
    'AI_COACH',
    'AI Debate Coach',
    'Personalized AI coaching based on user performance',
    30,
    0,
    1
),
(
    'AI_JUDGE',
    'AI Judge',
    'AI evaluates and scores debate performance',
    0,
    0,
    0
);
GO


/* ============================================================
   DEFAULT SUBSCRIPTION PLANS
   ============================================================ */

INSERT INTO SubscriptionPlans
(
    PlanCode,
    PlanName,
    Description,
    Price,
    DurationDays,
    MonthlyCredits
)
VALUES
(
    'FREE',
    'Free',
    'Basic free plan',
    0,
    30,
    100
),
(
    'PREMIUM',
    'Premium',
    'Premium plan with additional AI features and credits',
    99000,
    30,
    1000
);
GO


/* ============================================================
   DEFAULT ACHIEVEMENTS
   ============================================================ */

INSERT INTO Achievements
(
    AchievementCode,
    Name,
    Description,
    ConditionType,
    ConditionValue
)
VALUES
(
    'FIRST_DEBATE',
    'First Debate',
    'Complete your first debate',
    'TOTAL_DEBATES',
    1
),
(
    'TEN_DEBATES',
    'Debate Beginner',
    'Complete 10 debates',
    'TOTAL_DEBATES',
    10
),
(
    'TEN_WINS',
    'Rising Debater',
    'Win 10 debates',
    'TOTAL_WINS',
    10
),
(
    'WIN_STREAK_5',
    'Hot Streak',
    'Win 5 debates consecutively',
    'WIN_STREAK',
    5
);
GO


/* ============================================================
   SAMPLE TOPICS
   ============================================================ */

INSERT INTO Topics
(
    Title,
    Description,
    Category,
    Difficulty,
    CreatedBy
)
VALUES
(
    'Artificial intelligence should replace traditional teachers',
    'Debate whether AI should replace traditional teachers in education.',
    'Education',
    'Medium',
    NULL
),
(
    'Social media does more harm than good',
    'Discuss the positive and negative social impacts of social media.',
    'Society',
    'Easy',
    NULL
),
(
    'University education should be free',
    'Debate whether university tuition should be publicly funded.',
    'Education',
    'Medium',
    NULL
),
(
    'AI development should be strictly regulated',
    'Debate whether governments should strictly regulate artificial intelligence development.',
    'Technology',
    'Hard',
    NULL
);
GO


/* ============================================================
   VERIFY TABLES
   ============================================================ */

SELECT
    TABLE_SCHEMA,
    TABLE_NAME
FROM INFORMATION_SCHEMA.TABLES
WHERE TABLE_TYPE = 'BASE TABLE'
ORDER BY TABLE_NAME;
GO


EXEC sp_rename
    'dbo.DebateCriteria',
    'DebateScoreWeight',
    'OBJECT';
GO

    USE DebatePracticePlatformDB;
GO

SELECT DB_NAME() AS CurrentDatabase;

SELECT TABLE_NAME
FROM INFORMATION_SCHEMA.TABLES
WHERE TABLE_NAME IN ('DebateCriteria', 'DebateScoreWeight');

USE DebatePracticePlatformDB;
GO

SELECT
    TABLE_SCHEMA,
    TABLE_NAME
FROM INFORMATION_SCHEMA.TABLES
WHERE TABLE_NAME IN ('DebateCriteria', 'DebateScoreWeight');

USE DebatePracticePlatformDB;
GO

SELECT
    fk.name AS ForeignKeyName,
    OBJECT_NAME(fk.parent_object_id) AS FromTable,
    OBJECT_NAME(fk.referenced_object_id) AS ToTable
FROM sys.foreign_keys fk
WHERE fk.name IN (
    'FK_JudgeScores_Criteria',
    'FK_ArgumentScores_Criteria',
    'FK_SkillStatistics_Criteria'
);

ALTER TABLE [DebateSessions] ADD [Difficulty] nvarchar(50) NULL;