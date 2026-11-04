-- Seed one login-ready account for each existing ADPP role in the development database.
-- PasswordHash values were generated and verified with BCrypt.Net-Next 4.0.3,
-- the same package and BCrypt.Verify method used by AuthService.
-- Existing rows are never updated. A conflicting existing email aborts the transaction.

USE [DebatePracticePlatformDB];
GO

SET NOCOUNT ON;
SET XACT_ABORT ON;

DECLARE @Seed TABLE
(
    Email NVARCHAR(255) NOT NULL PRIMARY KEY,
    FullName NVARCHAR(150) NOT NULL,
    RoleName NVARCHAR(50) NOT NULL UNIQUE,
    PasswordHash NVARCHAR(500) NOT NULL
);

INSERT INTO @Seed (Email, FullName, RoleName, PasswordHash)
VALUES
    (N'admin@test.com',     N'Test Admin',     N'Admin',     N'$2a$11$x6G5hvy9TZ44jDB5e1fhceO7YjVSStn0XoJPGR9ZEOeffGS5P9OfW'),
    (N'lecturer@test.com',  N'Test Lecturer',  N'Lecturer',  N'$2a$11$q2LG6lHMG8j/croixct1Qe/tBGs8geqn9oIzudoIH1nUiq4yLhuYu'),
    (N'member@test.com',    N'Test Member',    N'Member',    N'$2a$11$9HheYj/7TgVc5/NZXigX9ebfw0CeAG61Ju1VC2WYECul2fqilhopO'),
    (N'moderator@test.com', N'Test Moderator', N'Moderator', N'$2a$11$BjMnNfS8anOA9dYZViaTNewMgRSd8OOPUL9YEfAypQ1NW3Pilbng.');

DECLARE @Inserted TABLE
(
    UserId INT NOT NULL PRIMARY KEY,
    Email NVARCHAR(255) NOT NULL UNIQUE
);

BEGIN TRY
    BEGIN TRANSACTION;

    IF DB_NAME() <> N'DebatePracticePlatformDB'
        THROW 51000, 'Unexpected target database.', 1;

    IF (SELECT COUNT(*) FROM @Seed AS s JOIN dbo.Roles AS r ON r.RoleName = s.RoleName) <> 4
        THROW 51001, 'All four existing ADPP roles are required.', 1;

    -- A prior run is accepted only if its users still match this seed exactly.
    -- A different hash cannot be verified by T-SQL, so never claim that an
    -- unrelated pre-existing account can log in with the seed password.
    IF EXISTS
    (
        SELECT 1
        FROM @Seed AS s
        JOIN dbo.Users AS u WITH (UPDLOCK, HOLDLOCK) ON u.Email = s.Email
        WHERE u.FullName <> s.FullName
           OR u.PasswordHash IS NULL
           OR u.PasswordHash <> s.PasswordHash
           OR u.IsActive <> 1
           OR u.IsEmailVerified <> 1
           OR NOT EXISTS
              (SELECT 1 FROM dbo.UserRoles AS ur JOIN dbo.Roles AS r ON r.RoleId = ur.RoleId
               WHERE ur.UserId = u.UserId AND r.RoleName = s.RoleName)
           OR EXISTS
              (SELECT 1 FROM dbo.UserRoles AS ur JOIN dbo.Roles AS r ON r.RoleId = ur.RoleId
               WHERE ur.UserId = u.UserId AND r.RoleName <> s.RoleName)
    )
        THROW 51002, 'A seed email already belongs to an account that differs from this seed. No existing user was changed.', 1;

    INSERT INTO dbo.Users
        (Email, FullName, PasswordHash, IsEmailVerified, IsActive, CreatedAt)
    OUTPUT inserted.UserId, inserted.Email INTO @Inserted (UserId, Email)
    SELECT s.Email, s.FullName, s.PasswordHash, 1, 1, SYSUTCDATETIME()
    FROM @Seed AS s
    WHERE NOT EXISTS
    (
        SELECT 1 FROM dbo.Users AS u WITH (UPDLOCK, HOLDLOCK)
        WHERE u.Email = s.Email
    );

    INSERT INTO dbo.UserRoles (UserId, RoleId, AssignedAt)
    SELECT i.UserId, r.RoleId, SYSUTCDATETIME()
    FROM @Inserted AS i
    JOIN @Seed AS s ON s.Email = i.Email
    JOIN dbo.Roles AS r ON r.RoleName = s.RoleName;

    IF EXISTS
    (
        SELECT 1
        FROM @Seed AS s
        LEFT JOIN dbo.Users AS u ON u.Email = s.Email
        WHERE u.UserId IS NULL
           OR u.FullName <> s.FullName
           OR u.PasswordHash IS NULL
           OR u.PasswordHash <> s.PasswordHash
           OR u.IsActive <> 1
           OR u.IsEmailVerified <> 1
           OR NOT EXISTS
              (SELECT 1 FROM dbo.UserRoles AS ur JOIN dbo.Roles AS r ON r.RoleId = ur.RoleId
               WHERE ur.UserId = u.UserId AND r.RoleName = s.RoleName)
           OR EXISTS
              (SELECT 1 FROM dbo.UserRoles AS ur JOIN dbo.Roles AS r ON r.RoleId = ur.RoleId
               WHERE ur.UserId = u.UserId AND r.RoleName <> s.RoleName)
    )
        THROW 51003, 'A seed user or its assigned role is missing or changed; changes rolled back.', 1;

    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF @@TRANCOUNT > 0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;

SELECT u.UserId, u.Email, u.FullName, r.RoleName AS [Role]
FROM @Seed AS s
JOIN dbo.Users AS u ON u.Email = s.Email
JOIN dbo.UserRoles AS ur ON ur.UserId = u.UserId
JOIN dbo.Roles AS r ON r.RoleId = ur.RoleId AND r.RoleName = s.RoleName
ORDER BY u.Email;
