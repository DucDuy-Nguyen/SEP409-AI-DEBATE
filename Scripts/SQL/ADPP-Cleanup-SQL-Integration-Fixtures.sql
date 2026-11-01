/*
    ADPP SQL Server integration-fixture cleanup proposal.

    Target: DebatePracticePlatformDB
    Review mode is the default: @CommitCleanup = 0 always rolls back.

    Safety properties:
      * Known IDs are accepted only when their email/title/session ownership
        relationships match the SqlServerCompetitionDebateTests fixture.
      * Dependent rows are discovered through their parent fixture IDs.
      * Unexpected incoming FK references abort the transaction.
      * FormatId 9 is preserved unless both explicit opt-in flags are enabled,
        its attributes match the temporary test format, and no external
        DebateSession/Competition references it.
      * This script has not been executed by Codex.
*/

USE [DebatePracticePlatformDB];
GO

SET NOCOUNT ON;
SET XACT_ABORT ON;

DECLARE @CommitCleanup bit = 0; -- Change to 1 only after separate review/approval.
DECLARE @DeleteFormat9 bit = 0; -- Optional catalog deletion; defaults to preserve.
DECLARE @ConfirmFormat9IsTestOwned bit = 0; -- Requires independent fixture-ownership evidence.

IF DB_NAME() <> N'DebatePracticePlatformDB'
BEGIN
    ;THROW 51000, N'Wrong database context. No cleanup was attempted.', 1;
END;

IF OBJECT_ID(N'dbo.Users', N'U') IS NULL
   OR OBJECT_ID(N'dbo.Competitions', N'U') IS NULL
   OR OBJECT_ID(N'dbo.CompetitionRounds', N'U') IS NULL
   OR OBJECT_ID(N'dbo.CompetitionMatches', N'U') IS NULL
   OR OBJECT_ID(N'dbo.CompetitionTeams', N'U') IS NULL
   OR OBJECT_ID(N'dbo.CompetitionTeamMembers', N'U') IS NULL
   OR OBJECT_ID(N'dbo.MatchParticipants', N'U') IS NULL
   OR OBJECT_ID(N'dbo.JudgeScores', N'U') IS NULL
   OR OBJECT_ID(N'dbo.DebateSessions', N'U') IS NULL
   OR OBJECT_ID(N'dbo.DebateParticipants', N'U') IS NULL
   OR OBJECT_ID(N'dbo.DebateRounds', N'U') IS NULL
   OR OBJECT_ID(N'dbo.Arguments', N'U') IS NULL
   OR OBJECT_ID(N'dbo.AIJudgements', N'U') IS NULL
   OR OBJECT_ID(N'dbo.DebateFormats', N'U') IS NULL
BEGIN
    ;THROW 51001, N'Required V0.61 tables are missing. No cleanup was attempted.', 1;
END;

SET TRANSACTION ISOLATION LEVEL SERIALIZABLE;

BEGIN TRY
    BEGIN TRANSACTION;

    CREATE TABLE #Tokens (Token char(32) NOT NULL PRIMARY KEY);
    CREATE TABLE #Users (UserId int NOT NULL PRIMARY KEY, Token char(32) NOT NULL, RoleName nvarchar(20) NOT NULL);
    CREATE TABLE #Competitions (CompetitionId int NOT NULL PRIMARY KEY, Token char(32) NOT NULL, CompetitionType nvarchar(30) NOT NULL);
    CREATE TABLE #CompetitionRounds (CompetitionRoundId int NOT NULL PRIMARY KEY, CompetitionId int NOT NULL);
    CREATE TABLE #Matches (CompetitionMatchId int NOT NULL PRIMARY KEY, CompetitionId int NOT NULL, CompetitionRoundId int NOT NULL);
    CREATE TABLE #Teams (TeamId int NOT NULL PRIMARY KEY, CompetitionId int NOT NULL, Token char(32) NOT NULL, TeamName nvarchar(150) NOT NULL);
    CREATE TABLE #TeamMembers (TeamMemberId bigint NOT NULL PRIMARY KEY, TeamId int NOT NULL, UserId int NOT NULL);
    CREATE TABLE #MatchParticipants (MatchParticipantId bigint NOT NULL PRIMARY KEY, CompetitionMatchId int NOT NULL, UserId int NULL, TeamId int NULL, Side nvarchar(10) NOT NULL);
    CREATE TABLE #JudgeScores (JudgeScoreId bigint NOT NULL PRIMARY KEY, CompetitionMatchId int NOT NULL);
    CREATE TABLE #Sessions (DebateSessionId int NOT NULL PRIMARY KEY, CreatedBy int NOT NULL, FormatId int NOT NULL);
    CREATE TABLE #DebateParticipants (ParticipantId int NOT NULL PRIMARY KEY, DebateSessionId int NOT NULL, UserId int NULL);
    CREATE TABLE #DebateRounds (RoundId int NOT NULL PRIMARY KEY, DebateSessionId int NOT NULL);
    CREATE TABLE #Arguments (ArgumentId int NOT NULL PRIMARY KEY, RoundId int NOT NULL, ParticipantId int NOT NULL);
    CREATE TABLE #AIJudgements (JudgementId int NOT NULL PRIMARY KEY, DebateSessionId int NOT NULL);
    CREATE TABLE #Formats (FormatId int NOT NULL PRIMARY KEY);
    CREATE TABLE #KnownCompetitionIds (Id int NOT NULL PRIMARY KEY);
    CREATE TABLE #KnownSessionIds (Id int NOT NULL PRIMARY KEY);
    CREATE TABLE #ExpectedRoles (RoleName nvarchar(20) NOT NULL PRIMARY KEY);

    INSERT #KnownCompetitionIds VALUES (19),(20),(21),(22),(23),(24),(25),(26),(27);
    INSERT #KnownSessionIds VALUES (32),(34),(35),(36),(37),(38),(39),(41),(42);
    INSERT #ExpectedRoles VALUES (N'organizer'),(N'judge'),(N'player1'),(N'player2'),(N'player3'),(N'player4'),(N'outsider');

    DECLARE @UserPatternCount int =
    (
        SELECT COUNT(*) FROM dbo.Users WHERE Email LIKE N'adpp-sql-it-%@example.invalid'
    );

    INSERT #Users (UserId, Token, RoleName)
    SELECT u.UserId, CONVERT(char(32), parsed.Token), CONVERT(nvarchar(20), parsed.RoleName)
    FROM dbo.Users AS u
    CROSS APPLY (VALUES (SUBSTRING(u.Email, 13, 32), SUBSTRING(u.Email, 46, LEN(u.Email) - 61))) AS parsed(Token, RoleName)
    WHERE u.Email LIKE N'adpp-sql-it-%@example.invalid'
      AND RIGHT(u.Email, 16) = N'@example.invalid'
      AND SUBSTRING(u.Email, 45, 1) = N'-'
      AND TRY_CONVERT(binary(16), parsed.Token, 2) IS NOT NULL
      AND parsed.RoleName IN (SELECT RoleName FROM #ExpectedRoles);

    INSERT #Tokens SELECT DISTINCT Token FROM #Users;

    IF @UserPatternCount <> 63 OR (SELECT COUNT(*) FROM #Users) <> 63
    BEGIN
        ;THROW 51002, N'Expected exactly 63 well-formed fixture users.', 1;
    END;
    IF (SELECT COUNT(*) FROM #Tokens) <> 9
    BEGIN
        ;THROW 51003, N'Expected exactly nine fixture tokens.', 1;
    END;
    IF EXISTS (SELECT Token FROM #Users GROUP BY Token HAVING COUNT(*) <> 7 OR COUNT(DISTINCT RoleName) <> 7)
       OR EXISTS (SELECT t.Token, r.RoleName FROM #Tokens AS t CROSS JOIN #ExpectedRoles AS r EXCEPT SELECT Token, RoleName FROM #Users)
    BEGIN
        ;THROW 51004, N'Fixture users do not have exactly the seven expected roles per token.', 1;
    END;

    INSERT #Competitions (CompetitionId, Token, CompetitionType)
    SELECT c.CompetitionId, u.Token, c.CompetitionType
    FROM dbo.Competitions AS c
    INNER JOIN #KnownCompetitionIds AS known ON known.Id = c.CompetitionId
    INNER JOIN #Users AS u ON u.UserId = c.CreatedBy AND u.RoleName = N'organizer'
    WHERE c.Title LIKE N'ADPP SQL test %'
      -- The fixture prefix has 14 characters, so the 32-character token starts at 15.
      AND SUBSTRING(c.Title, 15, 32) = u.Token
      AND SUBSTRING(c.Title, 47, 1) = N' '
      AND SUBSTRING(c.Title, 48, 20) IN (N'TEAM', N'INDIVIDUAL');

    IF (SELECT COUNT(*) FROM #Competitions) <> 9
       OR EXISTS (SELECT Id FROM #KnownCompetitionIds EXCEPT SELECT CompetitionId FROM #Competitions)
       OR EXISTS (SELECT CompetitionId FROM #Competitions EXCEPT SELECT Id FROM #KnownCompetitionIds)
    BEGIN
        ;THROW 51005, N'Competition IDs 19-27 failed fixture title and organizer ownership checks.', 1;
    END;
    IF (SELECT COUNT(*) FROM #Competitions WHERE CompetitionType = N'TEAM') <> 2
       OR (SELECT COUNT(*) FROM #Competitions WHERE CompetitionType = N'INDIVIDUAL') <> 7
    BEGIN
        ;THROW 51006, N'Fixture competition type counts differ from the recorded test suite.', 1;
    END;
    IF EXISTS
    (
        SELECT 1 FROM dbo.Competitions AS c
        INNER JOIN #Users AS u ON u.UserId = c.CreatedBy AND u.RoleName = N'organizer'
        WHERE NOT EXISTS (SELECT 1 FROM #Competitions AS f WHERE f.CompetitionId = c.CompetitionId)
    )
    BEGIN
        ;THROW 51007, N'A fixture organizer owns another competition outside the reported set.', 1;
    END;

    INSERT #CompetitionRounds
    SELECT r.CompetitionRoundId, r.CompetitionId FROM dbo.CompetitionRounds AS r
    INNER JOIN #Competitions AS c ON c.CompetitionId = r.CompetitionId;
    IF (SELECT COUNT(*) FROM #CompetitionRounds) <> 9
       OR EXISTS (SELECT 1 FROM dbo.CompetitionRounds AS r INNER JOIN #CompetitionRounds AS f ON f.CompetitionRoundId = r.CompetitionRoundId WHERE r.RoundName <> N'ADPP SQL test round')
       OR EXISTS (SELECT c.CompetitionId FROM #Competitions AS c LEFT JOIN #CompetitionRounds AS r ON r.CompetitionId = c.CompetitionId GROUP BY c.CompetitionId HAVING COUNT(r.CompetitionRoundId) <> 1)
    BEGIN
        ;THROW 51008, N'Each fixture competition must have exactly its expected test round.', 1;
    END;

    INSERT #Matches
    SELECT m.CompetitionMatchId, m.CompetitionId, m.CompetitionRoundId FROM dbo.CompetitionMatches AS m
    INNER JOIN #Competitions AS c ON c.CompetitionId = m.CompetitionId;
    IF (SELECT COUNT(*) FROM #Matches) <> 9
       OR EXISTS (SELECT c.CompetitionId FROM #Competitions AS c LEFT JOIN #Matches AS m ON m.CompetitionId = c.CompetitionId GROUP BY c.CompetitionId HAVING COUNT(m.CompetitionMatchId) <> 1)
       OR EXISTS (SELECT 1 FROM dbo.CompetitionMatches AS m INNER JOIN #Matches AS f ON f.CompetitionMatchId = m.CompetitionMatchId WHERE m.MatchNumber <> 1 OR m.BracketPosition <> 1)
       OR EXISTS (SELECT 1 FROM dbo.CompetitionMatches AS m INNER JOIN #Matches AS f ON f.CompetitionMatchId = m.CompetitionMatchId LEFT JOIN #Users AS j ON j.UserId = m.AssignedJudgeUserId AND j.RoleName = N'judge' WHERE j.UserId IS NULL)
    BEGIN
        ;THROW 51009, N'Competition matches do not match the expected fixture rows and assigned judges.', 1;
    END;

    INSERT #Teams
    SELECT t.TeamId, t.CompetitionId, c.Token, t.TeamName FROM dbo.CompetitionTeams AS t
    INNER JOIN #Competitions AS c ON c.CompetitionId = t.CompetitionId;
    IF (SELECT COUNT(*) FROM #Teams) <> 4
       OR EXISTS (SELECT 1 FROM #Teams AS t INNER JOIN #Competitions AS c ON c.CompetitionId = t.CompetitionId WHERE c.CompetitionType <> N'TEAM' OR t.TeamName NOT IN (N'ADPP ' + t.Token + N' PRO', N'ADPP ' + t.Token + N' CON'))
       OR EXISTS (SELECT c.CompetitionId FROM #Competitions AS c LEFT JOIN #Teams AS t ON t.CompetitionId = c.CompetitionId WHERE c.CompetitionType = N'TEAM' GROUP BY c.CompetitionId HAVING COUNT(t.TeamId) <> 2)
    BEGIN
        ;THROW 51010, N'The four teams do not match fixture competition tokens and names.', 1;
    END;

    INSERT #TeamMembers
    SELECT tm.TeamMemberId, tm.TeamId, tm.UserId FROM dbo.CompetitionTeamMembers AS tm
    INNER JOIN #Teams AS t ON t.TeamId = tm.TeamId;
    IF (SELECT COUNT(*) FROM #TeamMembers) <> 4
       OR EXISTS (SELECT t.TeamId FROM #Teams AS t LEFT JOIN #TeamMembers AS m ON m.TeamId = t.TeamId GROUP BY t.TeamId HAVING COUNT(m.TeamMemberId) <> 1)
       OR EXISTS (SELECT 1 FROM #TeamMembers AS m INNER JOIN #Teams AS t ON t.TeamId = m.TeamId LEFT JOIN #Users AS u ON u.UserId = m.UserId AND u.Token = t.Token AND u.RoleName = CASE WHEN t.TeamName LIKE N'% PRO' THEN N'player3' ELSE N'player4' END WHERE u.UserId IS NULL)
    BEGIN
        ;THROW 51011, N'Team members do not match the fixture-owned team/member relationships.', 1;
    END;

    INSERT #MatchParticipants
    SELECT p.MatchParticipantId, p.CompetitionMatchId, p.UserId, p.TeamId, p.Side
    FROM dbo.MatchParticipants AS p INNER JOIN #Matches AS m ON m.CompetitionMatchId = p.CompetitionMatchId;
    IF (SELECT COUNT(*) FROM #MatchParticipants) <> 18
       OR EXISTS
       (
           SELECT m.CompetitionMatchId FROM #Matches AS m
           INNER JOIN #Competitions AS c ON c.CompetitionId = m.CompetitionId
           LEFT JOIN #MatchParticipants AS p ON p.CompetitionMatchId = m.CompetitionMatchId
           GROUP BY m.CompetitionMatchId, c.CompetitionType
           HAVING COUNT(p.MatchParticipantId) <> 2
               OR SUM(CASE WHEN p.Side = N'PRO' THEN 1 ELSE 0 END) <> 1
               OR SUM(CASE WHEN p.Side = N'CON' THEN 1 ELSE 0 END) <> 1
       )
       OR EXISTS
       (
           SELECT 1 FROM #MatchParticipants AS p
           INNER JOIN #Matches AS m ON m.CompetitionMatchId = p.CompetitionMatchId
           INNER JOIN #Competitions AS c ON c.CompetitionId = m.CompetitionId
           LEFT JOIN #Users AS u ON u.UserId = p.UserId AND u.Token = c.Token
           LEFT JOIN #Teams AS t ON t.TeamId = p.TeamId AND t.CompetitionId = c.CompetitionId
           WHERE (c.CompetitionType = N'INDIVIDUAL' AND (u.UserId IS NULL OR p.TeamId IS NOT NULL))
              OR (c.CompetitionType = N'TEAM' AND (t.TeamId IS NULL OR p.UserId IS NOT NULL))
       )
    BEGIN
        ;THROW 51012, N'MatchParticipants do not match the expected fixture 1v1/team participants.', 1;
    END;

    INSERT #Sessions
    SELECT DISTINCT s.DebateSessionId, s.CreatedBy, s.FormatId
    FROM dbo.DebateSessions AS s
    WHERE EXISTS (SELECT 1 FROM #Users AS u WHERE u.UserId = s.CreatedBy AND u.RoleName = N'organizer')
       OR EXISTS (SELECT 1 FROM #Matches AS m INNER JOIN dbo.CompetitionMatches AS cm ON cm.CompetitionMatchId = m.CompetitionMatchId WHERE cm.DebateSessionId = s.DebateSessionId);
    IF (SELECT COUNT(*) FROM #Sessions) <> 9
       OR EXISTS (SELECT Id FROM #KnownSessionIds EXCEPT SELECT DebateSessionId FROM #Sessions)
       OR EXISTS (SELECT DebateSessionId FROM #Sessions EXCEPT SELECT Id FROM #KnownSessionIds)
       OR EXISTS (SELECT 1 FROM #Sessions AS s LEFT JOIN #Users AS u ON u.UserId = s.CreatedBy AND u.RoleName = N'organizer' WHERE u.UserId IS NULL)
    BEGIN
        ;THROW 51013, N'The nine reported DebateSession IDs are not owned by fixture organizers.', 1;
    END;
    IF (SELECT COUNT(*) FROM dbo.CompetitionMatches AS cm INNER JOIN #Matches AS m ON m.CompetitionMatchId = cm.CompetitionMatchId INNER JOIN #Sessions AS s ON s.DebateSessionId = cm.DebateSessionId) <> 8
       OR (SELECT COUNT(*) FROM #Sessions AS s WHERE NOT EXISTS (SELECT 1 FROM dbo.CompetitionMatches AS cm INNER JOIN #Matches AS m ON m.CompetitionMatchId = cm.CompetitionMatchId WHERE cm.DebateSessionId = s.DebateSessionId)) <> 1
    BEGIN
        ;THROW 51014, N'Expected eight linked fixture sessions and one valid standalone fixture session.', 1;
    END;

    INSERT #DebateRounds SELECT r.RoundId, r.DebateSessionId FROM dbo.DebateRounds AS r INNER JOIN #Sessions AS s ON s.DebateSessionId = r.DebateSessionId;
    IF (SELECT COUNT(*) FROM #DebateRounds) <> 27
       OR EXISTS (SELECT s.DebateSessionId FROM #Sessions AS s LEFT JOIN #DebateRounds AS r ON r.DebateSessionId = s.DebateSessionId GROUP BY s.DebateSessionId HAVING COUNT(r.RoundId) <> 3)
    BEGIN
        ;THROW 51015, N'Expected exactly three DebateRounds per fixture session.', 1;
    END;

    INSERT #DebateParticipants SELECT p.ParticipantId, p.DebateSessionId, p.UserId FROM dbo.DebateParticipants AS p INNER JOIN #Sessions AS s ON s.DebateSessionId = p.DebateSessionId;
    IF (SELECT COUNT(*) FROM #DebateParticipants) <> 22
       OR EXISTS (SELECT 1 FROM #DebateParticipants AS p LEFT JOIN #Users AS u ON u.UserId = p.UserId WHERE u.UserId IS NULL)
       OR EXISTS (SELECT s.DebateSessionId FROM #Sessions AS s LEFT JOIN #DebateParticipants AS p ON p.DebateSessionId = s.DebateSessionId GROUP BY s.DebateSessionId, s.FormatId HAVING COUNT(p.ParticipantId) <> CASE WHEN s.FormatId = 9 THEN 4 ELSE 2 END)
    BEGIN
        ;THROW 51016, N'DebateParticipants do not match the fixture session owners and format sizes.', 1;
    END;

    INSERT #Arguments SELECT a.ArgumentId, a.RoundId, a.ParticipantId FROM dbo.Arguments AS a INNER JOIN #DebateRounds AS r ON r.RoundId = a.RoundId;
    IF (SELECT COUNT(*) FROM #Arguments) <> 6 OR EXISTS (SELECT 1 FROM #Arguments AS a LEFT JOIN #DebateParticipants AS p ON p.ParticipantId = a.ParticipantId WHERE p.ParticipantId IS NULL)
    BEGIN
        ;THROW 51017, N'Expected the six argument rows created by the completion fixture.', 1;
    END;

    INSERT #AIJudgements SELECT j.JudgementId, j.DebateSessionId FROM dbo.AIJudgements AS j INNER JOIN #Sessions AS s ON s.DebateSessionId = j.DebateSessionId;
    INSERT #JudgeScores SELECT j.JudgeScoreId, j.CompetitionMatchId FROM dbo.JudgeScores AS j INNER JOIN #Matches AS m ON m.CompetitionMatchId = j.CompetitionMatchId;
    IF EXISTS (SELECT 1 FROM #AIJudgements) OR EXISTS (SELECT 1 FROM #JudgeScores)
    BEGIN
        ;THROW 51018, N'Unexpected AIJudgements or JudgeScores exist for these fixtures.', 1;
    END;

    DECLARE @ExternalFormatSessions int =
    (
        SELECT COUNT(*) FROM dbo.DebateSessions AS s WHERE s.FormatId = 9
          AND NOT EXISTS (SELECT 1 FROM #Sessions AS f WHERE f.DebateSessionId = s.DebateSessionId)
    );
    DECLARE @ExternalFormatCompetitions int =
    (
        SELECT COUNT(*) FROM dbo.Competitions AS c WHERE c.FormatId = 9
          AND NOT EXISTS (SELECT 1 FROM #Competitions AS f WHERE f.CompetitionId = c.CompetitionId)
    );
    IF @DeleteFormat9 = 1
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM dbo.DebateFormats WHERE FormatId = 9 AND FormatName = N'2 vs 2' AND MaxParticipants = 4 AND TotalRounds = 3 AND RoundDurationSeconds = 180 AND IsActive = 1)
        BEGIN
            ;THROW 51019, N'FormatId 9 does not match the temporary 2v2 fixture format.', 1;
        END;
        IF (SELECT COUNT(*) FROM #Sessions WHERE FormatId = 9) <> 2
           OR (SELECT COUNT(*) FROM dbo.Competitions AS c INNER JOIN #Competitions AS f ON f.CompetitionId = c.CompetitionId WHERE c.FormatId = 9) <> 2
        BEGIN
            ;THROW 51020, N'FormatId 9 is not referenced by the two expected team fixtures.', 1;
        END;
        IF @ConfirmFormat9IsTestOwned <> 1
        BEGIN
            ;THROW 51021, N'FormatId 9 deletion requires explicit confirmation of fixture ownership.', 1;
        END;
        IF @ExternalFormatSessions <> 0 OR @ExternalFormatCompetitions <> 0
        BEGIN
            ;THROW 51022, N'FormatId 9 has non-fixture references and cannot be deleted.', 1;
        END;
        INSERT #Formats (FormatId) VALUES (9);
    END;

    /* A fixture-owned user must not be linked from an unrelated competition/session/team/match. */
    IF EXISTS (SELECT 1 FROM dbo.Competitions AS c INNER JOIN #Users AS u ON u.UserId = c.CreatedBy WHERE NOT EXISTS (SELECT 1 FROM #Competitions AS f WHERE f.CompetitionId = c.CompetitionId))
       OR EXISTS (SELECT 1 FROM dbo.DebateSessions AS s INNER JOIN #Users AS u ON u.UserId = s.CreatedBy WHERE NOT EXISTS (SELECT 1 FROM #Sessions AS f WHERE f.DebateSessionId = s.DebateSessionId))
       OR EXISTS (SELECT 1 FROM dbo.DebateParticipants AS p INNER JOIN #Users AS u ON u.UserId = p.UserId WHERE NOT EXISTS (SELECT 1 FROM #Sessions AS f WHERE f.DebateSessionId = p.DebateSessionId))
       OR EXISTS (SELECT 1 FROM dbo.CompetitionMatches AS m INNER JOIN #Sessions AS s ON s.DebateSessionId = m.DebateSessionId WHERE NOT EXISTS (SELECT 1 FROM #Matches AS f WHERE f.CompetitionMatchId = m.CompetitionMatchId))
       OR EXISTS (SELECT 1 FROM dbo.CompetitionTeams AS t INNER JOIN #Users AS u ON u.UserId = t.CaptainUserId WHERE NOT EXISTS (SELECT 1 FROM #Teams AS f WHERE f.TeamId = t.TeamId))
       OR EXISTS (SELECT 1 FROM dbo.CompetitionTeamMembers AS tm INNER JOIN #Users AS u ON u.UserId = tm.UserId WHERE NOT EXISTS (SELECT 1 FROM #Teams AS f WHERE f.TeamId = tm.TeamId))
       OR EXISTS (SELECT 1 FROM dbo.MatchParticipants AS p INNER JOIN #Users AS u ON u.UserId = p.UserId WHERE NOT EXISTS (SELECT 1 FROM #Matches AS f WHERE f.CompetitionMatchId = p.CompetitionMatchId))
       OR EXISTS (SELECT 1 FROM dbo.JudgeScores AS s INNER JOIN #Users AS u ON u.UserId = s.JudgeUserId WHERE NOT EXISTS (SELECT 1 FROM #Matches AS f WHERE f.CompetitionMatchId = s.CompetitionMatchId))
       OR EXISTS (SELECT 1 FROM dbo.CompetitionMatches AS m INNER JOIN #Users AS u ON u.UserId IN (m.AssignedJudgeUserId, m.WinnerUserId) WHERE NOT EXISTS (SELECT 1 FROM #Matches AS f WHERE f.CompetitionMatchId = m.CompetitionMatchId))
    BEGIN
        ;THROW 51023, N'A fixture user is referenced by a non-fixture competition/debate relationship.', 1;
    END;

    /* Reject inbound FK rows that this script has not explicitly classified/deleted. */
    CREATE TABLE #OwnedKeys (ParentObjectId int NOT NULL, EntityId bigint NOT NULL, PRIMARY KEY (ParentObjectId, EntityId));
    INSERT #OwnedKeys
    SELECT OBJECT_ID(N'dbo.Users'), UserId FROM #Users
    UNION ALL SELECT OBJECT_ID(N'dbo.Competitions'), CompetitionId FROM #Competitions
    UNION ALL SELECT OBJECT_ID(N'dbo.CompetitionRounds'), CompetitionRoundId FROM #CompetitionRounds
    UNION ALL SELECT OBJECT_ID(N'dbo.CompetitionMatches'), CompetitionMatchId FROM #Matches
    UNION ALL SELECT OBJECT_ID(N'dbo.CompetitionTeams'), TeamId FROM #Teams
    UNION ALL SELECT OBJECT_ID(N'dbo.DebateSessions'), DebateSessionId FROM #Sessions
    UNION ALL SELECT OBJECT_ID(N'dbo.DebateParticipants'), ParticipantId FROM #DebateParticipants
    UNION ALL SELECT OBJECT_ID(N'dbo.DebateRounds'), RoundId FROM #DebateRounds
    UNION ALL SELECT OBJECT_ID(N'dbo.Arguments'), ArgumentId FROM #Arguments
    UNION ALL SELECT OBJECT_ID(N'dbo.MatchParticipants'), MatchParticipantId FROM #MatchParticipants
    UNION ALL SELECT OBJECT_ID(N'dbo.AIJudgements'), JudgementId FROM #AIJudgements
    UNION ALL SELECT OBJECT_ID(N'dbo.DebateFormats'), FormatId FROM #Formats WHERE @DeleteFormat9 = 1;

    CREATE TABLE #HandledFK (ParentObjectId int, ChildObjectId int, FKName sysname, PRIMARY KEY (ParentObjectId, ChildObjectId, FKName));
    INSERT #HandledFK VALUES
      (OBJECT_ID(N'dbo.Users'), OBJECT_ID(N'dbo.Competitions'), N'FK_Competitions_CreatedBy'),
      (OBJECT_ID(N'dbo.Users'), OBJECT_ID(N'dbo.DebateSessions'), N'FK_DebateSessions_CreatedBy'),
      (OBJECT_ID(N'dbo.Users'), OBJECT_ID(N'dbo.DebateParticipants'), N'FK_DebateParticipants_User'),
      (OBJECT_ID(N'dbo.Users'), OBJECT_ID(N'dbo.CompetitionTeams'), N'FK_CompetitionTeams_Captain'),
      (OBJECT_ID(N'dbo.Users'), OBJECT_ID(N'dbo.CompetitionTeamMembers'), N'FK_CompetitionTeamMembers_User'),
      (OBJECT_ID(N'dbo.Users'), OBJECT_ID(N'dbo.MatchParticipants'), N'FK_MatchParticipants_User'),
      (OBJECT_ID(N'dbo.Users'), OBJECT_ID(N'dbo.JudgeScores'), N'FK_JudgeScores_Judge'),
      (OBJECT_ID(N'dbo.Users'), OBJECT_ID(N'dbo.CompetitionMatches'), N'FK_CompetitionMatches_AssignedJudge'),
      (OBJECT_ID(N'dbo.Users'), OBJECT_ID(N'dbo.CompetitionMatches'), N'FK_CompetitionMatches_WinnerUser'),
      (OBJECT_ID(N'dbo.Competitions'), OBJECT_ID(N'dbo.CompetitionRounds'), N'FK_CompetitionRounds_Competition'),
      (OBJECT_ID(N'dbo.Competitions'), OBJECT_ID(N'dbo.CompetitionTeams'), N'FK_CompetitionTeams_Competition'),
      (OBJECT_ID(N'dbo.Competitions'), OBJECT_ID(N'dbo.CompetitionMatches'), N'FK_CompetitionMatches_Competition'),
      (OBJECT_ID(N'dbo.CompetitionRounds'), OBJECT_ID(N'dbo.CompetitionMatches'), N'FK_CompetitionMatches_Round'),
      (OBJECT_ID(N'dbo.CompetitionTeams'), OBJECT_ID(N'dbo.CompetitionTeamMembers'), N'FK_CompetitionTeamMembers_Team'),
      (OBJECT_ID(N'dbo.CompetitionTeams'), OBJECT_ID(N'dbo.MatchParticipants'), N'FK_MatchParticipants_Team'),
      (OBJECT_ID(N'dbo.CompetitionTeams'), OBJECT_ID(N'dbo.CompetitionMatches'), N'FK_CompetitionMatches_WinnerTeam'),
      (OBJECT_ID(N'dbo.CompetitionMatches'), OBJECT_ID(N'dbo.MatchParticipants'), N'FK_MatchParticipants_Match'),
      (OBJECT_ID(N'dbo.CompetitionMatches'), OBJECT_ID(N'dbo.JudgeScores'), N'FK_JudgeScores_Match'),
      (OBJECT_ID(N'dbo.DebateSessions'), OBJECT_ID(N'dbo.DebateParticipants'), N'FK_DebateParticipants_Session'),
      (OBJECT_ID(N'dbo.DebateSessions'), OBJECT_ID(N'dbo.DebateRounds'), N'FK_DebateRounds_Session'),
      (OBJECT_ID(N'dbo.DebateSessions'), OBJECT_ID(N'dbo.AIJudgements'), N'FK_AIJudgements_Session'),
      (OBJECT_ID(N'dbo.DebateSessions'), OBJECT_ID(N'dbo.CompetitionMatches'), N'FK_CompetitionMatches_DebateSession'),
      (OBJECT_ID(N'dbo.DebateParticipants'), OBJECT_ID(N'dbo.Arguments'), N'FK_Arguments_Participant'),
      (OBJECT_ID(N'dbo.DebateParticipants'), OBJECT_ID(N'dbo.AIJudgements'), N'FK_AIJudgements_Winner'),
      (OBJECT_ID(N'dbo.DebateRounds'), OBJECT_ID(N'dbo.Arguments'), N'FK_Arguments_Round'),
      (OBJECT_ID(N'dbo.MatchParticipants'), OBJECT_ID(N'dbo.JudgeScores'), N'FK_JudgeScores_Participant'),
      (OBJECT_ID(N'dbo.DebateFormats'), OBJECT_ID(N'dbo.DebateSessions'), N'FK_DebateSessions_Formats'),
      (OBJECT_ID(N'dbo.DebateFormats'), OBJECT_ID(N'dbo.Competitions'), N'FK_Competitions_Format');

    DECLARE @FKGuard nvarchar(max) = N'';
    SELECT @FKGuard = @FKGuard + N'
IF EXISTS (SELECT 1 FROM ' + QUOTENAME(OBJECT_SCHEMA_NAME(fk.parent_object_id)) + N'.' + QUOTENAME(OBJECT_NAME(fk.parent_object_id)) + N' AS child
INNER JOIN #OwnedKeys AS owned ON owned.ParentObjectId = ' + CONVERT(nvarchar(20), fk.referenced_object_id) + N'
AND TRY_CONVERT(bigint, child.' + QUOTENAME(childColumn.name) + N') = owned.EntityId)
BEGIN
    ;THROW 51024, N''Unexpected inbound FK rows in ' + REPLACE(OBJECT_SCHEMA_NAME(fk.parent_object_id) + N'.' + OBJECT_NAME(fk.parent_object_id) + N' via ' + fk.name, N'''', N'''''') + N'. Cleanup aborted.'', 1;
END;
'
    FROM sys.foreign_keys AS fk
    INNER JOIN sys.foreign_key_columns AS fkc ON fkc.constraint_object_id = fk.object_id
    INNER JOIN sys.columns AS childColumn ON childColumn.object_id = fkc.parent_object_id AND childColumn.column_id = fkc.parent_column_id
    WHERE fk.referenced_object_id IN (SELECT DISTINCT ParentObjectId FROM #OwnedKeys)
      AND NOT EXISTS (SELECT 1 FROM #HandledFK AS h WHERE h.ParentObjectId = fk.referenced_object_id AND h.ChildObjectId = fk.parent_object_id AND h.FKName = fk.name);
    IF LEN(@FKGuard) > 0 EXEC sys.sp_executesql @FKGuard;

    /* Pre-delete audit: exact derived tokens and IDs plus the actual FK graph. */
    SELECT Token FROM #Tokens ORDER BY Token;
    SELECT u.UserId, u.Token, u.RoleName, db.Email FROM #Users AS u INNER JOIN dbo.Users AS db ON db.UserId = u.UserId ORDER BY u.Token, u.RoleName;
    SELECT c.CompetitionId, c.Token, c.CompetitionType, db.Title, db.CreatedBy FROM #Competitions AS c INNER JOIN dbo.Competitions AS db ON db.CompetitionId = c.CompetitionId ORDER BY c.CompetitionId;
    SELECT * FROM #CompetitionRounds ORDER BY CompetitionRoundId;
    SELECT * FROM #Matches ORDER BY CompetitionMatchId;
    SELECT * FROM #Teams ORDER BY TeamId;
    SELECT * FROM #TeamMembers ORDER BY TeamMemberId;
    SELECT * FROM #MatchParticipants ORDER BY MatchParticipantId;
    SELECT * FROM #Sessions ORDER BY DebateSessionId;
    SELECT * FROM #DebateParticipants ORDER BY ParticipantId;
    SELECT * FROM #DebateRounds ORDER BY RoundId;
    SELECT * FROM #Arguments ORDER BY ArgumentId;
    SELECT * FROM #AIJudgements ORDER BY JudgementId;
    SELECT * FROM #JudgeScores ORDER BY JudgeScoreId;
    SELECT @ExternalFormatSessions AS NonFixtureSessionsReferencingFormat9,
           @ExternalFormatCompetitions AS NonFixtureCompetitionsReferencingFormat9;
    SELECT CAST(9 AS int) AS FormatId,
           CASE WHEN EXISTS (SELECT 1 FROM dbo.DebateFormats WHERE FormatId = 9) THEN CAST(1 AS bit) ELSE CAST(0 AS bit) END AS ExistsBeforeCleanup,
           @DeleteFormat9 AS SelectedForDeletion,
           CASE WHEN @DeleteFormat9 = 1 THEN N'Selected for deletion if all guards pass' ELSE N'Preserved; deletion is disabled' END AS CleanupTreatment;
    SELECT FormatId AS SelectedFormatId FROM #Formats ORDER BY FormatId;

    SELECT Entity, ExpectedRows, ActualRows FROM
    (
        SELECT N'Users' AS Entity, 63 AS ExpectedRows, COUNT(*) AS ActualRows FROM #Users
        UNION ALL SELECT N'Competitions', 9, COUNT(*) FROM #Competitions
        UNION ALL SELECT N'CompetitionRounds', 9, COUNT(*) FROM #CompetitionRounds
        UNION ALL SELECT N'CompetitionMatches', 9, COUNT(*) FROM #Matches
        UNION ALL SELECT N'CompetitionTeams', 4, COUNT(*) FROM #Teams
        UNION ALL SELECT N'CompetitionTeamMembers', 4, COUNT(*) FROM #TeamMembers
        UNION ALL SELECT N'MatchParticipants', 18, COUNT(*) FROM #MatchParticipants
        UNION ALL SELECT N'JudgeScores', 0, COUNT(*) FROM #JudgeScores
        UNION ALL SELECT N'DebateSessions', 9, COUNT(*) FROM #Sessions
        UNION ALL SELECT N'DebateParticipants', 22, COUNT(*) FROM #DebateParticipants
        UNION ALL SELECT N'DebateRounds', 27, COUNT(*) FROM #DebateRounds
        UNION ALL SELECT N'Arguments', 6, COUNT(*) FROM #Arguments
        UNION ALL SELECT N'AIJudgements', 0, COUNT(*) FROM #AIJudgements
    ) AS counts ORDER BY Entity;

    SELECT OBJECT_SCHEMA_NAME(fk.referenced_object_id) + N'.' + OBJECT_NAME(fk.referenced_object_id) AS ReferencedParent,
           OBJECT_SCHEMA_NAME(fk.parent_object_id) + N'.' + OBJECT_NAME(fk.parent_object_id) AS ReferencingChild,
           fk.name AS ForeignKeyName, fk.delete_referential_action_desc AS OnDeleteAction
    FROM sys.foreign_keys AS fk WHERE fk.referenced_object_id IN (SELECT ParentObjectId FROM #OwnedKeys)
    ORDER BY ReferencedParent, ReferencingChild, ForeignKeyName;

    CREATE TABLE #DeletedRows (EntityName sysname NOT NULL, EntityId bigint NOT NULL);

    /* FK-safe deletion order; every target comes from a validated fixture-owned ID set. */
    DELETE a OUTPUT N'Arguments', CONVERT(bigint, DELETED.ArgumentId) INTO #DeletedRows FROM dbo.Arguments AS a INNER JOIN #Arguments AS f ON f.ArgumentId = a.ArgumentId;
    DELETE j OUTPUT N'AIJudgements', CONVERT(bigint, DELETED.JudgementId) INTO #DeletedRows FROM dbo.AIJudgements AS j INNER JOIN #AIJudgements AS f ON f.JudgementId = j.JudgementId;
    DELETE p OUTPUT N'DebateParticipants', CONVERT(bigint, DELETED.ParticipantId) INTO #DeletedRows FROM dbo.DebateParticipants AS p INNER JOIN #DebateParticipants AS f ON f.ParticipantId = p.ParticipantId;
    DELETE r OUTPUT N'DebateRounds', CONVERT(bigint, DELETED.RoundId) INTO #DeletedRows FROM dbo.DebateRounds AS r INNER JOIN #DebateRounds AS f ON f.RoundId = r.RoundId;

    UPDATE cm SET DebateSessionId = NULL
    OUTPUT N'CompetitionMatches.UnlinkedSession', CONVERT(bigint, DELETED.CompetitionMatchId) INTO #DeletedRows
    FROM dbo.CompetitionMatches AS cm INNER JOIN #Matches AS f ON f.CompetitionMatchId = cm.CompetitionMatchId
    WHERE cm.DebateSessionId IS NOT NULL;

    DELETE s OUTPUT N'DebateSessions', CONVERT(bigint, DELETED.DebateSessionId) INTO #DeletedRows FROM dbo.DebateSessions AS s INNER JOIN #Sessions AS f ON f.DebateSessionId = s.DebateSessionId;
    DELETE s OUTPUT N'JudgeScores', CONVERT(bigint, DELETED.JudgeScoreId) INTO #DeletedRows FROM dbo.JudgeScores AS s INNER JOIN #JudgeScores AS f ON f.JudgeScoreId = s.JudgeScoreId;
    DELETE p OUTPUT N'MatchParticipants', CONVERT(bigint, DELETED.MatchParticipantId) INTO #DeletedRows FROM dbo.MatchParticipants AS p INNER JOIN #MatchParticipants AS f ON f.MatchParticipantId = p.MatchParticipantId;
    DELETE m OUTPUT N'CompetitionMatches', CONVERT(bigint, DELETED.CompetitionMatchId) INTO #DeletedRows FROM dbo.CompetitionMatches AS m INNER JOIN #Matches AS f ON f.CompetitionMatchId = m.CompetitionMatchId;
    DELETE tm OUTPUT N'CompetitionTeamMembers', CONVERT(bigint, DELETED.TeamMemberId) INTO #DeletedRows FROM dbo.CompetitionTeamMembers AS tm INNER JOIN #TeamMembers AS f ON f.TeamMemberId = tm.TeamMemberId;
    DELETE t OUTPUT N'CompetitionTeams', CONVERT(bigint, DELETED.TeamId) INTO #DeletedRows FROM dbo.CompetitionTeams AS t INNER JOIN #Teams AS f ON f.TeamId = t.TeamId;
    DELETE r OUTPUT N'CompetitionRounds', CONVERT(bigint, DELETED.CompetitionRoundId) INTO #DeletedRows FROM dbo.CompetitionRounds AS r INNER JOIN #CompetitionRounds AS f ON f.CompetitionRoundId = r.CompetitionRoundId;
    DELETE c OUTPUT N'Competitions', CONVERT(bigint, DELETED.CompetitionId) INTO #DeletedRows FROM dbo.Competitions AS c INNER JOIN #Competitions AS f ON f.CompetitionId = c.CompetitionId;
    IF @DeleteFormat9 = 1
    BEGIN
        DELETE fmt OUTPUT N'DebateFormats', CONVERT(bigint, DELETED.FormatId) INTO #DeletedRows FROM dbo.DebateFormats AS fmt INNER JOIN #Formats AS f ON f.FormatId = fmt.FormatId;
    END;
    DELETE u OUTPUT N'Users', CONVERT(bigint, DELETED.UserId) INTO #DeletedRows FROM dbo.Users AS u INNER JOIN #Users AS f ON f.UserId = u.UserId;

    IF EXISTS (SELECT 1 FROM dbo.Users AS x INNER JOIN #Users AS f ON f.UserId = x.UserId)
       OR EXISTS (SELECT 1 FROM dbo.Competitions AS x INNER JOIN #Competitions AS f ON f.CompetitionId = x.CompetitionId)
       OR EXISTS (SELECT 1 FROM dbo.CompetitionRounds AS x INNER JOIN #CompetitionRounds AS f ON f.CompetitionRoundId = x.CompetitionRoundId)
       OR EXISTS (SELECT 1 FROM dbo.CompetitionMatches AS x INNER JOIN #Matches AS f ON f.CompetitionMatchId = x.CompetitionMatchId)
       OR EXISTS (SELECT 1 FROM dbo.CompetitionTeams AS x INNER JOIN #Teams AS f ON f.TeamId = x.TeamId)
       OR EXISTS (SELECT 1 FROM dbo.CompetitionTeamMembers AS x INNER JOIN #TeamMembers AS f ON f.TeamMemberId = x.TeamMemberId)
       OR EXISTS (SELECT 1 FROM dbo.MatchParticipants AS x INNER JOIN #MatchParticipants AS f ON f.MatchParticipantId = x.MatchParticipantId)
       OR EXISTS (SELECT 1 FROM dbo.JudgeScores AS x INNER JOIN #JudgeScores AS f ON f.JudgeScoreId = x.JudgeScoreId)
       OR EXISTS (SELECT 1 FROM dbo.DebateSessions AS x INNER JOIN #Sessions AS f ON f.DebateSessionId = x.DebateSessionId)
       OR EXISTS (SELECT 1 FROM dbo.DebateParticipants AS x INNER JOIN #DebateParticipants AS f ON f.ParticipantId = x.ParticipantId)
       OR EXISTS (SELECT 1 FROM dbo.DebateRounds AS x INNER JOIN #DebateRounds AS f ON f.RoundId = x.RoundId)
       OR EXISTS (SELECT 1 FROM dbo.Arguments AS x INNER JOIN #Arguments AS f ON f.ArgumentId = x.ArgumentId)
       OR EXISTS (SELECT 1 FROM dbo.AIJudgements AS x INNER JOIN #AIJudgements AS f ON f.JudgementId = x.JudgementId)
       OR (@DeleteFormat9 = 1 AND EXISTS (SELECT 1 FROM dbo.DebateFormats WHERE FormatId = 9))
    BEGIN
        ;THROW 51025, N'Post-delete verification found fixture rows still present; the transaction will roll back.', 1;
    END;

    SELECT EntityName, COUNT(*) AS RowsAffected FROM #DeletedRows GROUP BY EntityName ORDER BY EntityName;
    IF @CommitCleanup = 1
    BEGIN
        COMMIT TRANSACTION;
        PRINT N'Cleanup committed by explicit @CommitCleanup = 1.';
    END
    ELSE
    BEGIN
        ROLLBACK TRANSACTION;
        PRINT N'Review only: all changes were rolled back because @CommitCleanup = 0.';
    END;
END TRY
BEGIN CATCH
    IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;
