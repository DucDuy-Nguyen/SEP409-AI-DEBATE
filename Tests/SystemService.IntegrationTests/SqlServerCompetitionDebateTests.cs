using System.Data;
using System.Data.Common;
using System.Threading;
using Microsoft.Data.SqlClient;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Diagnostics;
using Microsoft.Extensions.Logging.Abstractions;
using System.Text.Json;
using SystemService.BLL.Services.AI.Implementations;
using SystemService.BLL.DTOs.Debate;
using SystemService.BLL.DTOs.Competition.Tournament;
using SystemService.BLL.DTOs.Competition.Management;
using SystemService.BLL.DTOs.Competition.Team;
using SystemService.BLL.Services.Competition.Implementations;
using SystemService.BLL.Services.Debate.Implementations;
using SystemService.DAL.Context;
using SystemService.DAL.Entities.Competition;
using SystemService.DAL.Entities.Debate;
using SystemService.DAL.Entities.Debate.Enums;
using SystemService.DAL.Entities.Identity;
using SystemService.DAL.Repositories.Competition.Implementations;
using SystemService.DAL.Repositories.Debate.Implementations;
using SystemService.DAL.Repositories.Identity.Implementations;
using Xunit;
using Xunit.Abstractions;

namespace SystemService.IntegrationTests;

[CollectionDefinition("SQL Server integration", DisableParallelization = true)]
public sealed class SqlServerIntegrationCollection
{
    public const string Name = "SQL Server integration";
}

public sealed class SqlServerFactAttribute : FactAttribute
{
    public SqlServerFactAttribute()
    {
        if (!string.Equals(Environment.GetEnvironmentVariable("ADPP_RUN_SQLSERVER_TESTS"), "1", StringComparison.Ordinal))
        {
            Skip = "Set ADPP_RUN_SQLSERVER_TESTS=1 to opt in to development SQL Server integration tests.";
        }
    }
}

public sealed class SqlServerLiveAiFactAttribute : FactAttribute
{
    public SqlServerLiveAiFactAttribute()
    {
        if (Environment.GetEnvironmentVariable("ADPP_RUN_SQLSERVER_TESTS") != "1"
            || Environment.GetEnvironmentVariable("ADPP_RUN_LIVE_AI_TESTS") != "1"
            || string.IsNullOrWhiteSpace(Environment.GetEnvironmentVariable("ADPP_AI_EVALUATOR_URL")))
            Skip = "Opt in with ADPP_RUN_SQLSERVER_TESTS=1, ADPP_RUN_LIVE_AI_TESTS=1 and ADPP_AI_EVALUATOR_URL.";
    }
}

[Collection(SqlServerIntegrationCollection.Name)]
public sealed class SqlServerCompetitionDebateTests
{
    private readonly ITestOutputHelper _output;

    public SqlServerCompetitionDebateTests(ITestOutputHelper output) => _output = output;

    [SqlServerFact]
    public async Task Prepare_FiveConcurrentRequests_CreateOneLinkedSessionWithoutOrphans()
    {
        await using var fixture = await SqlFixture.CreateAsync();
        var match = await fixture.CreateMatchAsync(team: false);
        using var start = new ManualResetEventSlim(false);
        using var ready = new CountdownEvent(5);

        var requests = Enumerable.Range(0, 5).Select(_ => Task.Run(async () =>
        {
            await using var context = fixture.CreateContext();
            var bridge = fixture.CreateBridge(context);
            ready.Signal();
            start.Wait();
            return await bridge.PrepareMatchDebateAsync(fixture.OrganizerId, match.MatchId, fixture.TopicId);
        })).ToArray();

        var allReady = ready.Wait(TimeSpan.FromSeconds(20));
        start.Set();
        Assert.True(allReady, "All five SQL Server contexts must be ready before releasing concurrent Prepare requests.");
        var results = await Task.WhenAll(requests);

        Assert.All(results, result => Assert.True(result.Success, result.Message));
        Assert.Single(results.Select(result => result.Data!.SessionId).Distinct());

        await using var verify = fixture.CreateContext();
        var storedMatch = await verify.CompetitionMatches.AsNoTracking().SingleAsync(m => m.CompetitionMatchId == match.MatchId);
        Assert.NotNull(storedMatch.DebateSessionId);
        var ownedSessions = await verify.DebateSessions.AsNoTracking()
            .Where(s => s.CreatedBy == fixture.OrganizerId && s.TopicId == fixture.TopicId)
            .ToListAsync();
        Assert.Single(ownedSessions);
        Assert.Equal(storedMatch.DebateSessionId, ownedSessions[0].DebateSessionId);
        var linkedIds = await verify.CompetitionMatches.AsNoTracking()
            .Where(m => m.CompetitionMatchId == match.MatchId && m.DebateSessionId.HasValue)
            .Select(m => m.DebateSessionId!.Value)
            .ToListAsync();
        Assert.Equal(ownedSessions.Select(session => session.DebateSessionId), linkedIds);
    }

    [SqlServerFact]
    public async Task CompetitionStart_OrganizerAndJudgeRace_OnlyOneTransitionIsPersisted()
    {
        await using var fixture = await SqlFixture.CreateAsync();
        var match = await fixture.CreateMatchAsync(team: false);
        int sessionId = await fixture.PrepareAsync(match);
        using var start = new ManualResetEventSlim(false);
        using var ready = new CountdownEvent(2);

        var organizerRequest = Task.Run(async () =>
        {
            await using var context = fixture.CreateContext();
            ready.Signal();
            start.Wait();
            return await fixture.CreateDebateService(context).StartDebateSessionAsync(fixture.OrganizerId, sessionId);
        });
        var judgeRequest = Task.Run(async () =>
        {
            await using var context = fixture.CreateContext();
            ready.Signal();
            start.Wait();
            return await fixture.CreateDebateService(context).StartDebateSessionAsync(fixture.JudgeId, sessionId);
        });

        var bothReady = ready.Wait(TimeSpan.FromSeconds(20));
        start.Set();
        Assert.True(bothReady, "Organizer and judge contexts must be ready before releasing concurrent Start requests.");
        var results = await Task.WhenAll(organizerRequest, judgeRequest);
        Assert.Single(results, result => result.Success);
        Assert.Single(results, result => !result.Success);
        Assert.Equal(SessionStatus.InProgress, results.Single(result => result.Success).Data!.Status);

        await using var verify = fixture.CreateContext();
        var session = await verify.DebateSessions.AsNoTracking().SingleAsync(s => s.DebateSessionId == sessionId);
        var matchState = await verify.CompetitionMatches.AsNoTracking().SingleAsync(m => m.CompetitionMatchId == match.MatchId);
        var rounds = await verify.DebateRounds.AsNoTracking().Where(r => r.DebateSessionId == sessionId).ToListAsync();
        Assert.Equal(SessionStatus.InProgress, session.Status);
        Assert.Equal("Ongoing", matchState.Status);
        Assert.NotNull(session.StartTime);
        Assert.Equal(session.StartTime, matchState.StartedAt);
        Assert.Equal(session.StartTime, Assert.Single(rounds, round => round.RoundNumber == 1).StartTime);
        Assert.Equal(3, rounds.Count);
    }

    [SqlServerFact]
    public async Task StandaloneStart_TwoConcurrentCreatorRequests_OnlyOneSucceeds()
    {
        await using var fixture = await SqlFixture.CreateAsync();
        var sessionId = await fixture.CreateStandaloneSessionAsync();
        using var start = new ManualResetEventSlim(false);
        using var ready = new CountdownEvent(2);

        var requests = Enumerable.Range(0, 2).Select(_ => Task.Run(async () =>
        {
            await using var context = fixture.CreateContext();
            ready.Signal();
            start.Wait();
            return await fixture.CreateDebateService(context).StartDebateSessionAsync(fixture.OrganizerId, sessionId);
        })).ToArray();

        var bothReady = ready.Wait(TimeSpan.FromSeconds(20));
        start.Set();
        Assert.True(bothReady, "Both standalone contexts must be ready before releasing concurrent Start requests.");
        var results = await Task.WhenAll(requests);
        Assert.Single(results, result => result.Success);
        Assert.Single(results, result => !result.Success);

        await using var verify = fixture.CreateContext();
        var session = await verify.DebateSessions.AsNoTracking().SingleAsync(s => s.DebateSessionId == sessionId);
        var firstRound = await verify.DebateRounds.AsNoTracking()
            .SingleAsync(r => r.DebateSessionId == sessionId && r.RoundNumber == 1);
        Assert.Equal(SessionStatus.InProgress, session.Status);
        Assert.NotNull(session.StartTime);
        Assert.Equal(session.StartTime, firstRound.StartTime);
        Assert.Equal(3, await verify.DebateRounds.CountAsync(r => r.DebateSessionId == sessionId));
    }

    [SqlServerFact]
    public async Task Prepare_RowVersionConflictRollsBackSessionRoundsAndParticipants()
    {
        await using var fixture = await SqlFixture.CreateAsync();
        var match = await fixture.CreateMatchAsync(team: false);
        var interceptor = new BumpMatchRowVersionAfterInsert(fixture.ConnectionString, match.MatchId);
        var options = fixture.CreateOptions(interceptor);

        await using (var context = new SystemDbContext(options))
        {
            var bridge = fixture.CreateBridge(context);
            var result = await bridge.PrepareMatchDebateAsync(fixture.OrganizerId, match.MatchId, fixture.TopicId);
            Assert.False(result.Success);
            Assert.Contains("Xung đột đồng thời", result.Message);
            Assert.True(interceptor.WasTriggered);
        }

        await using var verify = fixture.CreateContext();
        var storedMatch = await verify.CompetitionMatches.AsNoTracking().SingleAsync(m => m.CompetitionMatchId == match.MatchId);
        Assert.Null(storedMatch.DebateSessionId);
        Assert.Equal(0, await verify.DebateSessions.CountAsync(s => s.CreatedBy == fixture.OrganizerId && s.TopicId == fixture.TopicId));
        Assert.Equal(0, await verify.DebateRounds.CountAsync(r => r.DebateSession.CreatedBy == fixture.OrganizerId));
        Assert.Equal(0, await verify.DebateParticipants.CountAsync(p => p.DebateSession.CreatedBy == fixture.OrganizerId));
    }

    [SqlServerFact]
    public async Task Prepare_IndividualMatch_MapsExactlyTwoUsersToFixedSides()
    {
        await using var fixture = await SqlFixture.CreateAsync();
        var match = await fixture.CreateMatchAsync(team: false);
        int sessionId = await fixture.PrepareAsync(match);

        await using var verify = fixture.CreateContext();
        var participants = await verify.DebateParticipants.AsNoTracking()
            .Where(p => p.DebateSessionId == sessionId)
            .ToListAsync();
        Assert.Equal(2, participants.Count);
        Assert.Equal(fixture.Player1Id, participants.Single(p => p.Side == DebateSide.PRO).UserId);
        Assert.Equal(fixture.Player2Id, participants.Single(p => p.Side == DebateSide.CON).UserId);
        Assert.Equal(3, await verify.DebateRounds.CountAsync(r => r.DebateSessionId == sessionId));
    }

    [SqlServerFact]
    public async Task Prepare_TeamMatch_MapsCaptainAndMemberToCorrectSides()
    {
        await using var fixture = await SqlFixture.CreateAsync();
        var match = await fixture.CreateMatchAsync(team: true);
        int sessionId = await fixture.PrepareAsync(match);

        await using var verify = fixture.CreateContext();
        var participants = await verify.DebateParticipants.AsNoTracking()
            .Where(p => p.DebateSessionId == sessionId)
            .ToListAsync();
        Assert.Equal(4, participants.Count);
        Assert.Equal(4, participants.Select(p => p.UserId).Distinct().Count());
        Assert.Equal(new[] { fixture.Player1Id, fixture.Player3Id }, participants
            .Where(p => p.Side == DebateSide.PRO).Select(p => p.UserId!.Value).Order().ToArray());
        Assert.Equal(new[] { fixture.Player2Id, fixture.Player4Id }, participants
            .Where(p => p.Side == DebateSide.CON).Select(p => p.UserId!.Value).Order().ToArray());
        Assert.Equal(3, await verify.DebateRounds.CountAsync(r => r.DebateSessionId == sessionId));
    }

    [SqlServerFact]
    public async Task FinalArgument_CompletesDebateAndMovesLinkedMatchToEvaluating()
    {
        await using var fixture = await SqlFixture.CreateAsync();
        var match = await fixture.CreateMatchAsync(team: false);
        int sessionId = await fixture.PrepareAsync(match);

        await using (var starterContext = fixture.CreateContext())
        {
            var start = await fixture.CreateDebateService(starterContext)
                .StartDebateSessionAsync(fixture.JudgeId, sessionId);
            Assert.True(start.Success, start.Message);
        }

        int conUserId;
        await using (var setup = fixture.CreateContext())
        {
            var participants = await setup.DebateParticipants.Where(p => p.DebateSessionId == sessionId).ToListAsync();
            var pro = participants.Single(p => p.Side == DebateSide.PRO);
            var con = participants.Single(p => p.Side == DebateSide.CON);
            conUserId = con.UserId!.Value;
            var rounds = await setup.DebateRounds.Where(r => r.DebateSessionId == sessionId)
                .OrderBy(r => r.RoundNumber).ToListAsync();

            foreach (var round in rounds.Take(2))
            {
                setup.Arguments.AddRange(
                    new Argument { RoundId = round.RoundId, ParticipantId = pro.ParticipantId, Content = "fixture pro", SubmittedAt = DateTime.UtcNow },
                    new Argument { RoundId = round.RoundId, ParticipantId = con.ParticipantId, Content = "fixture con", SubmittedAt = DateTime.UtcNow.AddMilliseconds(1) });
            }
            setup.Arguments.Add(new Argument
            {
                RoundId = rounds[2].RoundId,
                ParticipantId = pro.ParticipantId,
                Content = "final fixture pro",
                SubmittedAt = DateTime.UtcNow
            });
            await setup.SaveChangesAsync();
        }

        await using (var submitContext = fixture.CreateContext())
        {
            var result = await fixture.CreateDebateService(submitContext).SubmitArgumentAsync(
                conUserId, sessionId, new SubmitArgumentRequest { Content = "final fixture con" });
            Assert.True(result.Success, result.Message);
            Assert.Equal(SessionStatus.Completed, result.Data!.Status);
        }

        await using var verify = fixture.CreateContext();
        var completed = await verify.DebateSessions.AsNoTracking().SingleAsync(s => s.DebateSessionId == sessionId);
        var completedMatch = await verify.CompetitionMatches.AsNoTracking().SingleAsync(m => m.CompetitionMatchId == match.MatchId);
        Assert.Equal(SessionStatus.Completed, completed.Status);
        Assert.NotNull(completed.EndTime);
        Assert.Equal("Evaluating", completedMatch.Status);
        Assert.NotNull(completedMatch.UpdatedAt);
        Assert.Null(completedMatch.CompletedAt);
    }

    [SqlServerFact]
    public async Task CompetitionSession_RejectsUnauthorizedStartJoinSwitchAndSwapRequests()
    {
        await using var fixture = await SqlFixture.CreateAsync();
        var individualMatch = await fixture.CreateMatchAsync(team: false);
        int individualSessionId = await fixture.PrepareAsync(individualMatch);

        await using (var context = fixture.CreateContext())
        {
            var service = fixture.CreateDebateService(context);
            Assert.False((await service.StartDebateSessionAsync(fixture.OutsiderId, individualSessionId)).Success);
            Assert.False((await service.JoinP2pSessionAsync(fixture.OutsiderId, individualSessionId, new JoinSessionRequest())).Success);
            Assert.False((await service.SwitchSideAsync(fixture.Player1Id, individualSessionId)).Success);
            Assert.False((await service.SendSwapSideRequestAsync(fixture.Player1Id, individualSessionId,
                new SendSwapSideRequest { TargetUserId = fixture.Player2Id })).Success);
        }

        var teamMatch = await fixture.CreateMatchAsync(team: true);
        int teamSessionId = await fixture.PrepareAsync(teamMatch);
        await using (var context = fixture.CreateContext())
        {
            var join = await fixture.CreateDebateService(context).Join2v2SessionAsync(
                fixture.OutsiderId, teamSessionId, new Join2v2SessionRequest());
            Assert.False(join.Success);
        }

        await using var verify = fixture.CreateContext();
        Assert.Equal(SessionStatus.Waiting, (await verify.DebateSessions.AsNoTracking().SingleAsync(s => s.DebateSessionId == individualSessionId)).Status);
        Assert.Equal("Ready", (await verify.CompetitionMatches.AsNoTracking().SingleAsync(m => m.CompetitionMatchId == individualMatch.MatchId)).Status);
        Assert.Equal(2, await verify.DebateParticipants.CountAsync(p => p.DebateSessionId == individualSessionId));
    }

    [SqlServerFact]
    public async Task Start_ChangeTrackerResponseAndPersistedSqlServerValuesAgree()
    {
        await using var fixture = await SqlFixture.CreateAsync();
        var match = await fixture.CreateMatchAsync(team: false);
        int sessionId = await fixture.PrepareAsync(match);

        await using var context = fixture.CreateContext();
        var result = await fixture.CreateDebateService(context).StartDebateSessionAsync(fixture.OrganizerId, sessionId);
        Assert.True(result.Success, result.Message);
        Assert.Equal(SessionStatus.InProgress, result.Data!.Status);
        Assert.NotNull(result.Data.StartedAt);

        var trackedSession = await context.DebateSessions.SingleAsync(s => s.DebateSessionId == sessionId);
        var trackedMatch = await context.CompetitionMatches.SingleAsync(m => m.CompetitionMatchId == match.MatchId);
        var trackedRound = await context.DebateRounds.SingleAsync(r => r.DebateSessionId == sessionId && r.RoundNumber == 1);
        Assert.Equal(SessionStatus.InProgress, trackedSession.Status);
        Assert.Equal("Ongoing", trackedMatch.Status);
        Assert.Equal(result.Data.StartedAt, trackedSession.StartTime);
        Assert.Equal(trackedSession.StartTime, trackedMatch.StartedAt);
        Assert.Equal(trackedSession.StartTime, trackedRound.StartTime);

        await using var verify = fixture.CreateContext();
        var persistedSession = await verify.DebateSessions.AsNoTracking().SingleAsync(s => s.DebateSessionId == sessionId);
        var persistedMatch = await verify.CompetitionMatches.AsNoTracking().SingleAsync(m => m.CompetitionMatchId == match.MatchId);
        var persistedRound = await verify.DebateRounds.AsNoTracking().SingleAsync(r => r.DebateSessionId == sessionId && r.RoundNumber == 1);
        Assert.Equal(result.Data.Status, persistedSession.Status);
        Assert.Equal("Ongoing", persistedMatch.Status);
        Assert.Equal(result.Data.StartedAt, persistedSession.StartTime);
        Assert.Equal(persistedSession.StartTime, persistedMatch.StartedAt);
        Assert.Equal(persistedSession.StartTime, persistedRound.StartTime);
    }

    [SqlServerFact]
    public async Task Tournament_ThreeIndividuals_ByeDebatesAndChampion()
    {
        await using var fixture = await SqlFixture.CreateAsync();
        var competitionId = await fixture.CreateTournamentAsync(team: false, entrantCount: 3);
        await using (var context = fixture.CreateContext())
        {
            var generated = await new CompetitionTournamentService(context).GenerateBracketAsync(competitionId, fixture.OrganizerId);
            Assert.True(generated.Success, generated.Message);
            Assert.Equal(2, generated.Data!.Rounds.Count);
            Assert.Equal(1, generated.Data.Rounds[0].Matches.Count(m => m.Status == "Bye"));
            Assert.Equal(1, generated.Data.Rounds[0].Matches.Count(m => m.Status == "Scheduled"));
            Assert.Equal(2, generated.Data.Rounds[0].Matches.Count);
        }

        await fixture.StartTournamentAsync(competitionId);
        int semifinalId;
        int finalId;
        await using (var context = fixture.CreateContext())
        {
            var rounds = await context.CompetitionRounds.AsNoTracking().Where(r => r.CompetitionId == competitionId)
                .OrderBy(r => r.RoundNumber).ToListAsync();
            semifinalId = await context.CompetitionMatches.AsNoTracking()
                .Where(m => m.CompetitionRoundId == rounds[0].CompetitionRoundId && m.Status == "Ready")
                .Select(m => m.CompetitionMatchId).SingleAsync();
            finalId = await context.CompetitionMatches.AsNoTracking()
                .Where(m => m.CompetitionRoundId == rounds[1].CompetitionRoundId)
                .Select(m => m.CompetitionMatchId).SingleAsync();
        }
        await fixture.PlayAndFinalizeAsync(competitionId, semifinalId);

        await using (var verify = fixture.CreateContext())
        {
            var next = await verify.CompetitionMatches.AsNoTracking().Include(m => m.Participants)
                .SingleAsync(m => m.CompetitionMatchId == finalId);
            Assert.Equal("Ready", next.Status);
            Assert.Equal(2, next.Participants.Count);
            Assert.Equal(1, next.Participants.Count(p => p.Side == "PRO"));
            Assert.Equal(1, next.Participants.Count(p => p.Side == "CON"));
            Assert.Null(next.DebateSessionId);
        }
        await fixture.PlayAndFinalizeAsync(competitionId, finalId);

        await using var finalCheck = fixture.CreateContext();
        var competition = await finalCheck.Competitions.AsNoTracking().SingleAsync(c => c.CompetitionId == competitionId);
        var final = await finalCheck.CompetitionMatches.AsNoTracking().SingleAsync(m => m.CompetitionMatchId == finalId);
        Assert.Equal("Completed", competition.Status);
        Assert.Equal("Completed", final.Status);
        Assert.NotNull(final.WinnerUserId);
        Assert.Null(final.WinnerTeamId);
        var bracket = await new CompetitionTournamentService(finalCheck).GetBracketAsync(competitionId);
        Assert.Equal(final.WinnerUserId, bracket.Data!.ChampionUserId);
    }

    [SqlServerFact]
    public async Task Tournament_TwoTeams_FourDistinctUsers_OfficialTeamChampion()
    {
        await using var fixture = await SqlFixture.CreateAsync();
        var competitionId = await fixture.CreateTournamentAsync(team: true, entrantCount: 2);
        await using (var context = fixture.CreateContext())
        {
            var result = await new CompetitionTournamentService(context).GenerateBracketAsync(competitionId, fixture.OrganizerId);
            Assert.True(result.Success, result.Message);
            Assert.Single(result.Data!.Rounds);
            Assert.Equal("Scheduled", Assert.Single(result.Data.Rounds[0].Matches).Status);
        }
        await fixture.StartTournamentAsync(competitionId);
        int matchId;
        await using (var context = fixture.CreateContext())
            matchId = await context.CompetitionMatches.Where(m => m.CompetitionId == competitionId)
                .Select(m => m.CompetitionMatchId).SingleAsync();
        await fixture.PlayAndFinalizeAsync(competitionId, matchId);
        await using var verify = fixture.CreateContext();
        var final = await verify.CompetitionMatches.AsNoTracking().SingleAsync(m => m.CompetitionMatchId == matchId);
        Assert.NotNull(final.WinnerTeamId);
        Assert.Null(final.WinnerUserId);
        Assert.Equal("Completed", (await verify.Competitions.AsNoTracking().SingleAsync(c => c.CompetitionId == competitionId)).Status);
        Assert.Equal(2, await verify.CompetitionTeamMembers.Where(tm =>
            verify.CompetitionTeams.Any(t => t.TeamId == tm.TeamId && t.CompetitionId == competitionId)).CountAsync());
    }

    [SqlServerFact]
    public async Task Tournament_ConcurrentGeneration_CreatesOneBracketWithoutPartialRounds()
    {
        await using var fixture = await SqlFixture.CreateAsync();
        var competitionId = await fixture.CreateTournamentAsync(team: false, entrantCount: 3);
        using var start = new ManualResetEventSlim(false);
        using var ready = new CountdownEvent(2);
        var attempts = Enumerable.Range(0, 2).Select(_ => Task.Run(async () =>
        {
            await using var context = fixture.CreateContext();
            ready.Signal();
            start.Wait();
            return await new CompetitionTournamentService(context).GenerateBracketAsync(competitionId, fixture.OrganizerId);
        })).ToArray();
        var bothReady = ready.Wait(TimeSpan.FromSeconds(20));
        start.Set();
        Assert.True(bothReady);
        var responses = await Task.WhenAll(attempts);
        Assert.Single(responses, response => response.Success);
        Assert.Single(responses, response => !response.Success);
        await using var verify = fixture.CreateContext();
        Assert.Equal(2, await verify.CompetitionRounds.CountAsync(r => r.CompetitionId == competitionId));
        Assert.Equal(3, await verify.CompetitionMatches.CountAsync(m => m.CompetitionId == competitionId));
    }

    [SqlServerFact]
    public async Task Tournament_ConcurrentCompetitionStart_OnlyOneRequestWins()
    {
        await using var fixture = await SqlFixture.CreateAsync();
        var competitionId = await fixture.CreateTournamentAsync(team: false, entrantCount: 3);
        await using (var context = fixture.CreateContext())
            Assert.True((await new CompetitionTournamentService(context).GenerateBracketAsync(competitionId, fixture.OrganizerId)).Success);
        using var start = new ManualResetEventSlim(false);
        using var ready = new CountdownEvent(2);
        var attempts = Enumerable.Range(0, 2).Select(_ => Task.Run(async () =>
        {
            await using var context = fixture.CreateContext();
            var service = new CompetitionService(new CompetitionRepository(context), new DebateFormatRepository(context),
                new UserRepository(context), new CompetitionRegistrationRepository(context), new CompetitionTeamRepository(context));
            ready.Signal();
            start.Wait();
            return await service.StartCompetitionAsync(competitionId, fixture.OrganizerId);
        })).ToArray();
        var bothReady = ready.Wait(TimeSpan.FromSeconds(20));
        start.Set();
        Assert.True(bothReady);
        var results = await Task.WhenAll(attempts);
        Assert.Single(results, result => result.Success);
        Assert.Single(results, result => !result.Success);
        await using var verify = fixture.CreateContext();
        Assert.Equal("Ongoing", (await verify.Competitions.AsNoTracking().SingleAsync(c => c.CompetitionId == competitionId)).Status);
        Assert.Single(await verify.CompetitionMatches.AsNoTracking()
            .Where(m => m.CompetitionId == competitionId && m.Status == "Ready").ToListAsync());
    }

    [SqlServerFact]
    public async Task Tournament_RejectsNonCreatorAndIncompleteTeamWithoutWritingBracket()
    {
        await using var fixture = await SqlFixture.CreateAsync();
        var competitionId = await fixture.CreateTournamentAsync(team: true, entrantCount: 2);
        await using (var context = fixture.CreateContext())
        {
            var service = new CompetitionTournamentService(context);
            Assert.False((await service.GenerateBracketAsync(competitionId, fixture.OutsiderId)).Success);
        }
        await using (var context = fixture.CreateContext())
        {
            var member = await context.CompetitionTeamMembers
                .FirstAsync(tm => context.CompetitionTeams.Any(t => t.TeamId == tm.TeamId && t.CompetitionId == competitionId));
            context.CompetitionTeamMembers.Remove(member);
            await context.SaveChangesAsync();
        }
        await using (var context = fixture.CreateContext())
        {
            var result = await new CompetitionTournamentService(context).GenerateBracketAsync(competitionId, fixture.OrganizerId);
            Assert.False(result.Success);
        }
        await using var verify = fixture.CreateContext();
        Assert.Equal(0, await verify.CompetitionRounds.CountAsync(r => r.CompetitionId == competitionId));
        Assert.Equal(0, await verify.CompetitionMatches.CountAsync(m => m.CompetitionId == competitionId));
    }

    [SqlServerLiveAiFact]
    public async Task Tournament_LiveAiEvaluation_HumanJudgeConfirmsChampion()
    {
        await using var fixture = await SqlFixture.CreateAsync();
        var competitionId = await fixture.CreateTournamentAsync(team: false, entrantCount: 2);
        await using (var context = fixture.CreateContext())
            Assert.True((await new CompetitionTournamentService(context).GenerateBracketAsync(competitionId, fixture.OrganizerId)).Success);
        await fixture.StartTournamentAsync(competitionId);
        int matchId;
        await using (var context = fixture.CreateContext())
            matchId = await context.CompetitionMatches.Where(m => m.CompetitionId == competitionId)
                .Select(m => m.CompetitionMatchId).SingleAsync();
        await fixture.PlayAndFinalizeAsync(competitionId, matchId, liveAi: true);
        await using var verify = fixture.CreateContext();
        Assert.Equal("Completed", (await verify.Competitions.AsNoTracking().SingleAsync(c => c.CompetitionId == competitionId)).Status);
        var sessionId = (await verify.CompetitionMatches.AsNoTracking().SingleAsync(m => m.CompetitionMatchId == matchId)).DebateSessionId;
        Assert.True(await verify.AIJudgements.AnyAsync(j => j.DebateSessionId == sessionId && j.AIProvider != "fixture"));
    }

    [SqlServerLiveAiFact]
    public async Task Tournament_LiveAiEvaluation_ThreeTeams_ByeScoresAndChampion()
    {
        await using var fixture = await SqlFixture.CreateAsync();
        var (competitionId, startDate) = await fixture.CreateAndRegisterTeamTournamentAsync();
        var remaining = startDate.AddMilliseconds(100) - DateTime.UtcNow;
        if (remaining > TimeSpan.Zero) await Task.Delay(remaining);
        await using (var context = fixture.CreateContext())
        {
            var generated = await new CompetitionTournamentService(context).GenerateBracketAsync(competitionId, fixture.OrganizerId);
            Assert.True(generated.Success, generated.Message);
            Assert.Equal(2, generated.Data!.Rounds.Count);
            Assert.Equal(1, generated.Data.Rounds[0].Matches.Count(m => m.Status == "Bye"));
        }

        await fixture.StartTournamentAsync(competitionId);
        for (var roundNumber = 1; roundNumber <= 2; roundNumber++)
        {
            int readyMatchId;
            await using (var context = fixture.CreateContext())
            {
                var roundId = await context.CompetitionRounds.AsNoTracking()
                    .Where(r => r.CompetitionId == competitionId && r.RoundNumber == roundNumber)
                    .Select(r => r.CompetitionRoundId).SingleAsync();
                readyMatchId = await context.CompetitionMatches.AsNoTracking()
                    .Where(m => m.CompetitionRoundId == roundId && m.Status == "Ready")
                    .Select(m => m.CompetitionMatchId).SingleAsync();
            }
            await fixture.PlayAndFinalizeAsync(competitionId, readyMatchId, liveAi: true);
        }

        await using var verify = fixture.CreateContext();
        var competition = await verify.Competitions.AsNoTracking().SingleAsync(c => c.CompetitionId == competitionId);
        var teams = await verify.CompetitionTeams.AsNoTracking().Include(t => t.TeamMembers)
            .Where(t => t.CompetitionId == competitionId).OrderBy(t => t.TeamId).ToListAsync();
        var rounds = await verify.CompetitionRounds.AsNoTracking()
            .Where(r => r.CompetitionId == competitionId).ToDictionaryAsync(r => r.CompetitionRoundId, r => r.RoundNumber);
        var matches = await verify.CompetitionMatches.AsNoTracking().Include(m => m.Participants)
            .Where(m => m.CompetitionId == competitionId).ToListAsync();
        var matchIds = matches.Select(m => m.CompetitionMatchId).ToList();
        var judgeScores = await verify.JudgeScores.AsNoTracking()
            .Where(s => matchIds.Contains(s.CompetitionMatchId)).ToListAsync();
        var sessionIds = matches.Where(m => m.DebateSessionId.HasValue).Select(m => m.DebateSessionId!.Value).ToList();
        var aiJudgements = await verify.AIJudgements.AsNoTracking()
            .Where(j => sessionIds.Contains(j.DebateSessionId)).ToListAsync();
        var final = matches.Single(m => !m.NextMatchId.HasValue);
        var bye = Assert.Single(matches, m => m.Status == "Bye");
        Assert.Equal(3, teams.Count);
        Assert.Equal(2, matches.Count(m => m.Status == "Completed"));
        Assert.Equal("Completed", competition.Status);
        Assert.NotNull(final.WinnerTeamId);
        Assert.NotNull(bye.WinnerTeamId);
        Assert.Null(bye.DebateSessionId);
        Assert.Equal(2, aiJudgements.Select(j => j.DebateSessionId).Distinct().Count());
        Assert.All(aiJudgements, j => Assert.NotEqual("fixture", j.AIProvider));
        Assert.All(matches.Where(m => m.Status == "Completed"), m =>
            Assert.All(m.Participants, p => Assert.NotNull(p.FinalScore)));

        var report = new
        {
            CompetitionId = competitionId,
            CompetitionStatus = competition.Status,
            TeamCount = teams.Count,
            Teams = teams.Select(t => new { t.TeamId, t.TeamName, t.CaptainUserId,
                MemberUserIds = t.TeamMembers.Select(member => member.UserId).ToArray() }).ToArray(),
            ByeTeamId = bye.WinnerTeamId,
            ChampionTeamId = final.WinnerTeamId,
            Matches = matches.OrderBy(m => rounds[m.CompetitionRoundId]).ThenBy(m => m.BracketPosition)
                .Select(m => new
                {
                    m.CompetitionMatchId,
                    RoundNumber = rounds[m.CompetitionRoundId],
                    m.BracketPosition,
                    m.Status,
                    m.NextMatchId,
                    m.DebateSessionId,
                    m.WinnerTeamId,
                    Participants = m.Participants.OrderBy(p => p.Side).Select(p => new
                    {
                        p.MatchParticipantId, p.TeamId, p.Side, p.SeedNumber, p.FinalScore, p.IsWinner,
                        JudgeScores = judgeScores.Where(s => s.MatchParticipantId == p.MatchParticipantId)
                            .OrderBy(s => s.CriteriaId).Select(s => new { s.CriteriaId, s.Score }).ToArray()
                    }).ToArray(),
                    AiJudgement = aiJudgements.Where(j => j.DebateSessionId == m.DebateSessionId)
                        .OrderByDescending(j => j.CreatedAt)
                        .Select(j => new { j.AIProvider, j.AIModel, j.SuggestedWinnerSide,
                            j.OverallScorePro, j.OverallScoreCon, j.ConfidenceScore }).FirstOrDefault()
                }).ToArray()
        };
        _output.WriteLine("ADPP_LIVE_AI_TOURNAMENT_REPORT=" + JsonSerializer.Serialize(report));
    }

    [SqlServerFact]
    public async Task Tournament_Individual_CreateRegisterApproveCloseThroughChampion()
    {
        await using var fixture = await SqlFixture.CreateAsync();
        var (competitionId, startDate) = await fixture.CreateAndRegisterIndividualTournamentAsync();
        var remaining = startDate.AddMilliseconds(100) - DateTime.UtcNow;
        if (remaining > TimeSpan.Zero) await Task.Delay(remaining);
        await using (var context = fixture.CreateContext())
        {
            var generated = await new CompetitionTournamentService(context).GenerateBracketAsync(competitionId, fixture.OrganizerId);
            Assert.True(generated.Success, generated.Message);
        }
        await fixture.StartTournamentAsync(competitionId);
        int matchId;
        await using (var context = fixture.CreateContext())
            matchId = await context.CompetitionMatches.Where(m => m.CompetitionId == competitionId)
                .Select(m => m.CompetitionMatchId).SingleAsync();
        await fixture.PlayAndFinalizeAsync(competitionId, matchId);
        await using var verify = fixture.CreateContext();
        Assert.Equal("Completed", (await verify.Competitions.AsNoTracking().SingleAsync(c => c.CompetitionId == competitionId)).Status);
        Assert.Equal(2, await verify.CompetitionRegistrations.CountAsync(r => r.CompetitionId == competitionId && r.Status == "Approved"));
    }

    [SqlServerFact]
    public async Task Tournament_ConcurrentJudgeFinalize_OneOfficialResultAndOneChampion()
    {
        await using var fixture = await SqlFixture.CreateAsync();
        var competitionId = await fixture.CreateTournamentAsync(team: false, entrantCount: 2);
        await using (var context = fixture.CreateContext())
            Assert.True((await new CompetitionTournamentService(context).GenerateBracketAsync(competitionId, fixture.OrganizerId)).Success);
        await fixture.StartTournamentAsync(competitionId);
        int matchId;
        await using (var context = fixture.CreateContext())
            matchId = await context.CompetitionMatches.Where(m => m.CompetitionId == competitionId)
                .Select(m => m.CompetitionMatchId).SingleAsync();
        var decision = await fixture.PlayAndFinalizeAsync(competitionId, matchId, finalize: false);
        using var start = new ManualResetEventSlim(false);
        using var ready = new CountdownEvent(2);
        var attempts = Enumerable.Range(0, 2).Select(_ => Task.Run(async () =>
        {
            await using var context = fixture.CreateContext();
            ready.Signal();
            start.Wait();
            return await new CompetitionTournamentService(context).FinalizeMatchAsync(competitionId, matchId, fixture.JudgeId, decision);
        })).ToArray();
        var bothReady = ready.Wait(TimeSpan.FromSeconds(20));
        start.Set();
        Assert.True(bothReady);
        var results = await Task.WhenAll(attempts);
        Assert.Single(results, result => result.Success);
        Assert.Single(results, result => !result.Success);
        await using var verify = fixture.CreateContext();
        Assert.Equal("Completed", (await verify.Competitions.AsNoTracking().SingleAsync(c => c.CompetitionId == competitionId)).Status);
        Assert.Equal(decision.Scores.Count, await verify.JudgeScores.CountAsync(s => s.CompetitionMatchId == matchId));
        Assert.Equal(1, await verify.MatchParticipants.CountAsync(p => p.CompetitionMatchId == matchId && p.IsWinner));
    }

    [SqlServerFact]
    public async Task Tournament_OnlyCreatorAssignsJudgeAndOnlyAssignedJudgeFinalizes()
    {
        await using var fixture = await SqlFixture.CreateAsync();
        var competitionId = await fixture.CreateTournamentAsync(team: false, entrantCount: 2);
        await using (var context = fixture.CreateContext())
            Assert.True((await new CompetitionTournamentService(context).GenerateBracketAsync(competitionId, fixture.OrganizerId)).Success);
        await fixture.StartTournamentAsync(competitionId);
        int matchId;
        await using (var context = fixture.CreateContext())
            matchId = await context.CompetitionMatches.Where(m => m.CompetitionId == competitionId)
                .Select(m => m.CompetitionMatchId).SingleAsync();
        await using (var context = fixture.CreateContext())
        {
            var denied = await new CompetitionTournamentService(context)
                .AssignJudgeAsync(competitionId, matchId, fixture.OutsiderId, fixture.JudgeId);
            Assert.False(denied.Success);
            Assert.Null((await context.CompetitionMatches.AsNoTracking().SingleAsync(m => m.CompetitionMatchId == matchId)).AssignedJudgeUserId);
        }
        var decision = await fixture.PlayAndFinalizeAsync(competitionId, matchId, finalize: false);
        await using (var context = fixture.CreateContext())
        {
            var denied = await new CompetitionTournamentService(context)
                .FinalizeMatchAsync(competitionId, matchId, fixture.OutsiderId, decision);
            Assert.False(denied.Success);
            Assert.Equal(0, await context.JudgeScores.CountAsync(s => s.CompetitionMatchId == matchId));
        }
        await using (var context = fixture.CreateContext())
        {
            var accepted = await new CompetitionTournamentService(context)
                .FinalizeMatchAsync(competitionId, matchId, fixture.JudgeId, decision);
            Assert.True(accepted.Success, accepted.Message);
        }
    }

    private sealed class SqlFixture : IAsyncDisposable
    {
        private readonly List<int> _userIds = new();
        private readonly List<int> _competitionIds = new();
        private readonly List<int> _roundIds = new();
        private readonly List<int> _matchIds = new();
        private readonly List<int> _teamIds = new();
        private readonly List<int> _createdFormatIds = new();
        private readonly List<int> _standaloneSessionIds = new();
        private readonly string _token = Guid.NewGuid().ToString("N");
        private readonly DbContextOptions<SystemDbContext> _options;

        private SqlFixture(string connectionString)
        {
            ConnectionString = connectionString;
            _options = new DbContextOptionsBuilder<SystemDbContext>()
                .UseSqlServer(connectionString, sql => sql.CommandTimeout(30))
                .Options;
        }

        public string ConnectionString { get; }
        public int OrganizerId { get; private set; }
        public int JudgeId { get; private set; }
        public int Player1Id { get; private set; }
        public int Player2Id { get; private set; }
        public int Player3Id { get; private set; }
        public int Player4Id { get; private set; }
        public int Player5Id { get; private set; }
        public int Player6Id { get; private set; }
        public int OutsiderId { get; private set; }
        public int TopicId { get; private set; }
        public int Format1v1Id { get; private set; }
        public int Format2v2Id { get; private set; }

        public SystemDbContext CreateContext() => new(_options);

        public DbContextOptions<SystemDbContext> CreateOptions(params IInterceptor[] interceptors)
        {
            var builder = new DbContextOptionsBuilder<SystemDbContext>()
                .UseSqlServer(ConnectionString, sql => sql.CommandTimeout(30));
            if (interceptors.Length > 0)
            {
                builder.AddInterceptors(interceptors);
            }
            return builder.Options;
        }

        public CompetitionDebateBridgeService CreateBridge(SystemDbContext context) =>
            new(context, new DebateRepository(context), new CompetitionTeamRepository(context));

        public DebateService CreateDebateService(SystemDbContext context) =>
            new(new DebateRepository(context), new UserRepository(context));

        public static async Task<SqlFixture> CreateAsync()
        {
            var connectionString = Environment.GetEnvironmentVariable("ADPP_SQLSERVER_TEST_CONNECTION_STRING");
            if (string.IsNullOrWhiteSpace(connectionString))
            {
                throw new InvalidOperationException("Set ADPP_SQLSERVER_TEST_CONNECTION_STRING to the SystemService User Secrets DefaultConnection before opting in.");
            }

            var fixture = new SqlFixture(connectionString);
            try
            {
                await fixture.ValidateTargetAndSchemaAsync();
                await fixture.CreateTestUsersAndResolveCatalogAsync();
                return fixture;
            }
            catch
            {
                await fixture.DisposeAsync();
                throw;
            }
        }

        private async Task ValidateTargetAndSchemaAsync()
        {
            var builder = new SqlConnectionStringBuilder(ConnectionString);
            if (!builder.IntegratedSecurity || !string.Equals(builder.InitialCatalog, "DebatePracticePlatformDB", StringComparison.OrdinalIgnoreCase))
            {
                throw new InvalidOperationException("SQL Server test connection must use Windows Integrated Authentication and target DebatePracticePlatformDB.");
            }

            await using var connection = new SqlConnection(ConnectionString);
            await connection.OpenAsync();
            await using (var command = connection.CreateCommand())
            {
                command.CommandText = "SELECT CONVERT(nvarchar(128),SERVERPROPERTY('MachineName')), CONVERT(nvarchar(128),SERVERPROPERTY('InstanceName')), DB_NAME(), ORIGINAL_LOGIN(), (SELECT auth_scheme FROM sys.dm_exec_connections WHERE session_id=@@SPID)";
                await using var reader = await command.ExecuteReaderAsync();
                Assert.True(await reader.ReadAsync());
                Assert.Equal("THANH-SANGG", reader.GetString(0));
                Assert.Equal("SQLEXPRESS", reader.GetString(1));
                Assert.Equal("DebatePracticePlatformDB", reader.GetString(2));
                Assert.False(reader.IsDBNull(3));
                Assert.Contains(reader.GetString(4), new[] { "NTLM", "KERBEROS" });
            }

            await using (var command = connection.CreateCommand())
            {
                command.CommandText = @"
SELECT
  (SELECT COUNT(*) FROM sys.tables t
     WHERE t.is_ms_shipped=0 AND NOT (SCHEMA_NAME(t.schema_id)=N'dbo' AND t.name=N'sysdiagrams')),
  (SELECT COUNT(*) FROM sys.key_constraints k JOIN sys.tables t ON t.object_id=k.parent_object_id
     WHERE k.type='PK' AND NOT (SCHEMA_NAME(t.schema_id)=N'dbo' AND t.name=N'sysdiagrams')),
  (SELECT COUNT(*) FROM sys.foreign_keys),
  (SELECT COUNT(*) FROM sys.columns c JOIN sys.tables t ON t.object_id=c.object_id
     WHERE (t.name='AIJudgements' AND c.name IN ('SuggestedWinnerSide','OverallScorePro','OverallScoreCon','ConfidenceScore','RawResponseJson'))
        OR (t.name='CompetitionMatches' AND c.name IN ('BracketPosition','NextMatchId','AssignedJudgeUserId','StartedAt','CompletedAt','RowVersion'))
        OR (t.name='MatchParticipants' AND c.name IN ('SeedNumber','FinalScore'))),
  (SELECT COUNT(*) FROM sys.indexes WHERE name IN ('UQ_CompetitionMatches_Round_Position','UQ_CompetitionTeamRequests_Pending')),
  (SELECT COUNT(*) FROM sys.columns c JOIN sys.tables t ON t.object_id=c.object_id WHERE t.name='CompetitionMatches' AND c.name='RowVersion' AND c.system_type_id=189 AND c.max_length=8 AND c.is_nullable=0)";
                await using var reader = await command.ExecuteReaderAsync();
                Assert.True(await reader.ReadAsync());
                Assert.Equal(43, reader.GetInt32(0));
                Assert.Equal(43, reader.GetInt32(1));
                Assert.True(reader.GetInt32(2) >= 70);
                Assert.Equal(13, reader.GetInt32(3));
                Assert.Equal(2, reader.GetInt32(4));
                Assert.Equal(1, reader.GetInt32(5));
            }
        }

        private async Task CreateTestUsersAndResolveCatalogAsync()
        {
            await using var context = CreateContext();
            var topic = await context.Topics.AsNoTracking().Where(t => t.IsActive).OrderBy(t => t.TopicId).FirstOrDefaultAsync()
                ?? throw new InvalidOperationException("No active seeded Debate Topic exists; refusing to write fixtures.");
            var format1v1 = await context.DebateFormats.AsNoTracking().SingleOrDefaultAsync(f => f.IsActive && f.FormatName == "1 vs 1")
                ?? throw new InvalidOperationException("Seeded active '1 vs 1' DebateFormat is missing; refusing to write fixtures.");
            var format2v2 = await context.DebateFormats.AsNoTracking().SingleOrDefaultAsync(f => f.IsActive && f.FormatName == "2 vs 2");

            TopicId = topic.TopicId;
            Format1v1Id = format1v1.FormatId;
            Format2v2Id = format2v2?.FormatId ?? 0;

            var users = new[]
            {
                NewUser("organizer"), NewUser("judge"), NewUser("player1"), NewUser("player2"),
                NewUser("player3"), NewUser("player4"), NewUser("player5"),
                NewUser("player6"), NewUser("outsider")
            };
            context.Users.AddRange(users);
            await context.SaveChangesAsync();
            _userIds.AddRange(users.Select(user => user.UserId));
            (OrganizerId, JudgeId, Player1Id, Player2Id, Player3Id, Player4Id, Player5Id, Player6Id, OutsiderId) =
                (users[0].UserId, users[1].UserId, users[2].UserId, users[3].UserId,
                    users[4].UserId, users[5].UserId, users[6].UserId, users[7].UserId, users[8].UserId);
            var lecturer = await context.Roles.AsNoTracking().SingleAsync(role => role.RoleName == "Lecturer");
            context.UserRoles.AddRange(new UserRole { UserId = JudgeId, RoleId = lecturer.RoleId },
                new UserRole { UserId = OrganizerId, RoleId = lecturer.RoleId });
            await context.SaveChangesAsync();
        }

        private User NewUser(string role) => new()
        {
            FullName = $"ADPP SQL test {role}",
            Email = $"adpp-sql-it-{_token}-{role}@example.invalid",
            PasswordHash = "integration-test-placeholder",
            IsActive = true
        };

        public async Task<MatchFixture> CreateMatchAsync(bool team)
        {
            await using var context = CreateContext();
            var now = DateTime.UtcNow;
            if (team && Format2v2Id == 0)
            {
                var inactiveFormatExists = await context.DebateFormats.AsNoTracking()
                    .AnyAsync(format => format.FormatName == "2 vs 2");
                if (inactiveFormatExists)
                {
                    throw new InvalidOperationException("An inactive '2 vs 2' DebateFormat exists; refusing to modify catalog data.");
                }

                var format = new DebateFormat
                {
                    FormatName = "2 vs 2",
                    MaxParticipants = 4,
                    TotalRounds = 3,
                    RoundDurationSeconds = 180,
                    IsActive = true,
                    CreatedAt = now
                };
                context.DebateFormats.Add(format);
                await context.SaveChangesAsync();
                Format2v2Id = format.FormatId;
                _createdFormatIds.Add(format.FormatId);
            }

            var competition = new Competition
            {
                Title = $"ADPP SQL test {_token} {(team ? "TEAM" : "INDIVIDUAL")}",
                CompetitionType = team ? "TEAM" : "INDIVIDUAL",
                CreatedBy = OrganizerId,
                FormatId = team ? Format2v2Id : Format1v1Id,
                RegistrationStart = now.AddDays(-2),
                RegistrationEnd = now.AddDays(-1),
                StartDate = now,
                Status = "Draft"
            };
            var round = new CompetitionRound
            {
                Competition = competition,
                RoundNumber = 1,
                RoundName = "ADPP SQL test round"
            };
            var match = new CompetitionMatch
            {
                Competition = competition,
                Round = round,
                MatchNumber = 1,
                BracketPosition = 1,
                AssignedJudgeUserId = JudgeId,
                Status = "Ready"
            };

            context.Competitions.Add(competition);
            context.CompetitionRounds.Add(round);
            context.CompetitionMatches.Add(match);

            if (team)
            {
                var proTeam = new CompetitionTeam { Competition = competition, TeamName = $"ADPP {_token} PRO", CaptainUserId = Player1Id };
                proTeam.TeamMembers.Add(new CompetitionTeamMember { Team = proTeam, UserId = Player3Id, JoinedAt = now });
                var conTeam = new CompetitionTeam { Competition = competition, TeamName = $"ADPP {_token} CON", CaptainUserId = Player2Id };
                conTeam.TeamMembers.Add(new CompetitionTeamMember { Team = conTeam, UserId = Player4Id, JoinedAt = now });
                context.CompetitionTeams.AddRange(proTeam, conTeam);
                context.MatchParticipants.AddRange(
                    new MatchParticipant { Match = match, Team = proTeam, Side = "PRO" },
                    new MatchParticipant { Match = match, Team = conTeam, Side = "CON" });
            }
            else
            {
                context.MatchParticipants.AddRange(
                    new MatchParticipant { Match = match, UserId = Player1Id, Side = "PRO" },
                    new MatchParticipant { Match = match, UserId = Player2Id, Side = "CON" });
            }

            await context.SaveChangesAsync();
            _competitionIds.Add(competition.CompetitionId);
            _roundIds.Add(round.CompetitionRoundId);
            _matchIds.Add(match.CompetitionMatchId);
            if (team)
            {
                _teamIds.AddRange(await context.CompetitionTeams.AsNoTracking()
                    .Where(t => t.CompetitionId == competition.CompetitionId).Select(t => t.TeamId).ToListAsync());
            }
            return new MatchFixture(match.CompetitionMatchId, competition.CompetitionId, round.CompetitionRoundId, team);
        }

        public async Task<int> CreateTournamentAsync(bool team, int entrantCount)
        {
            await using var context = CreateContext();
            var now = DateTime.UtcNow;
            if (team && Format2v2Id == 0)
            {
                if (await context.DebateFormats.AsNoTracking().AnyAsync(f => f.FormatName == "2 vs 2"))
                    throw new InvalidOperationException("An inactive 2 vs 2 format exists; fixture will not modify catalog records.");
                var format = new DebateFormat { FormatName = "2 vs 2", MaxParticipants = 4,
                    TotalRounds = 3, RoundDurationSeconds = 180, IsActive = true, CreatedAt = now };
                context.DebateFormats.Add(format);
                await context.SaveChangesAsync();
                Format2v2Id = format.FormatId;
                _createdFormatIds.Add(format.FormatId);
            }
            var competition = new Competition
            {
                Title = $"ADPP SQL test {_token} tournament {(team ? "TEAM" : "INDIVIDUAL")}",
                CompetitionType = team ? "TEAM" : "INDIVIDUAL", CreatedBy = OrganizerId,
                FormatId = team ? Format2v2Id : Format1v1Id, MaxParticipants = team ? entrantCount * 2 : entrantCount,
                RegistrationStart = now.AddDays(-2), RegistrationEnd = now.AddDays(-1),
                StartDate = now.AddHours(-1), Status = "RegistrationClosed", CreatedAt = now
            };
            context.Competitions.Add(competition);
            await context.SaveChangesAsync();
            _competitionIds.Add(competition.CompetitionId);
            if (team)
            {
                var pro = new CompetitionTeam { CompetitionId = competition.CompetitionId,
                    TeamName = $"ADPP {_token} team PRO", CaptainUserId = Player1Id, Status = "Active" };
                pro.TeamMembers.Add(new CompetitionTeamMember { UserId = Player3Id });
                var con = new CompetitionTeam { CompetitionId = competition.CompetitionId,
                    TeamName = $"ADPP {_token} team CON", CaptainUserId = Player2Id, Status = "Active" };
                con.TeamMembers.Add(new CompetitionTeamMember { UserId = Player4Id });
                context.CompetitionTeams.AddRange(pro, con);
                await context.SaveChangesAsync();
                _teamIds.AddRange(new[] { pro.TeamId, con.TeamId });
            }
            else
            {
                var ids = new[] { Player1Id, Player2Id, Player3Id, Player4Id }.Take(entrantCount);
                context.CompetitionRegistrations.AddRange(ids.Select(id => new CompetitionRegistration
                {
                    CompetitionId = competition.CompetitionId, UserId = id, Status = "Approved", RegisteredAt = now.AddDays(-2)
                }));
                await context.SaveChangesAsync();
            }
            return competition.CompetitionId;
        }

        public async Task<(int CompetitionId, DateTime StartDate)> CreateAndRegisterTeamTournamentAsync()
        {
            var now = DateTime.UtcNow;
            var registrationEnd = now.AddSeconds(30);
            var startDate = registrationEnd.AddSeconds(2);
            await using (var setup = CreateContext())
            {
                if (Format2v2Id == 0)
                {
                    if (await setup.DebateFormats.AsNoTracking().AnyAsync(f => f.FormatName == "2 vs 2"))
                        throw new InvalidOperationException("An inactive 2 vs 2 format exists; fixture will not modify catalog records.");
                    var format = new DebateFormat { FormatName = "2 vs 2", MaxParticipants = 4,
                        TotalRounds = 3, RoundDurationSeconds = 180, IsActive = true, CreatedAt = now };
                    setup.DebateFormats.Add(format);
                    await setup.SaveChangesAsync();
                    Format2v2Id = format.FormatId;
                    _createdFormatIds.Add(format.FormatId);
                }
            }

            int competitionId;
            await using (var context = CreateContext())
            {
                var service = new CompetitionService(new CompetitionRepository(context), new DebateFormatRepository(context),
                    new UserRepository(context), new CompetitionRegistrationRepository(context), new CompetitionTeamRepository(context));
                var created = await service.CreateAsync(OrganizerId, new CreateCompetitionRequest
                {
                    Title = $"ADPP SQL test {_token} full TEAM workflow", CompetitionType = "TEAM",
                    FormatId = Format2v2Id, MaxParticipants = 6,
                    RegistrationStart = now.AddMinutes(-1), RegistrationEnd = registrationEnd, StartDate = startDate
                });
                Assert.True(created.Success, created.Message);
                competitionId = created.Data!.CompetitionId;
                _competitionIds.Add(competitionId);
                var opened = await service.OpenRegistrationAsync(competitionId, OrganizerId);
                Assert.True(opened.Success, opened.Message);
            }

            var players = new[] { (Player1Id, Player3Id), (Player2Id, Player4Id),
                (Player5Id, Player6Id) };
            Assert.Equal(6, players.SelectMany(pair => new[] { pair.Item1, pair.Item2 }).Distinct().Count());
            for (var index = 0; index < players.Length; index++)
            {
                await using var context = CreateContext();
                var teams = new CompetitionTeamService(new CompetitionTeamRepository(context), new CompetitionRepository(context),
                    new CompetitionRegistrationRepository(context), new UserRepository(context));
                var requests = new CompetitionTeamRequestService(new CompetitionTeamRequestRepository(context),
                    new CompetitionTeamRepository(context), new CompetitionRepository(context), new UserRepository(context));
                var (captainId, memberId) = players[index];
                var team = await teams.CreateTeamAsync(competitionId, captainId,
                    new CreateCompetitionTeamRequest { TeamName = $"ADPP {_token} team {index + 1}" });
                Assert.True(team.Success, team.Message);
                _teamIds.Add(team.Data!.TeamId);
                var invitation = await requests.SendInvitationAsync(competitionId, team.Data.TeamId, captainId,
                    new SendTeamInvitationRequest { UserId = memberId });
                Assert.True(invitation.Success, invitation.Message);
                var accepted = await requests.AcceptInvitationAsync(competitionId, invitation.Data!.RequestId, memberId);
                Assert.True(accepted.Success, accepted.Message);
            }

            await using (var verify = CreateContext())
            {
                var teams = await verify.CompetitionTeams.AsNoTracking().Include(team => team.Captain)
                    .Include(team => team.TeamMembers).ThenInclude(member => member.User)
                    .Where(team => team.CompetitionId == competitionId).ToListAsync();
                Assert.Equal(3, teams.Count);
                Assert.All(teams, team =>
                {
                    Assert.Equal("Active", team.Status);
                    Assert.True(team.Captain.IsActive);
                    var member = Assert.Single(team.TeamMembers);
                    Assert.True(member.User.IsActive);
                    Assert.NotEqual(team.CaptainUserId, member.UserId);
                });
                Assert.Equal(6, teams.SelectMany(team => new[] { team.CaptainUserId, team.TeamMembers.Single().UserId })
                    .Distinct().Count());
            }

            await using (var context = CreateContext())
            {
                var service = new CompetitionService(new CompetitionRepository(context), new DebateFormatRepository(context),
                    new UserRepository(context), new CompetitionRegistrationRepository(context), new CompetitionTeamRepository(context));
                var closed = await service.CloseRegistrationAsync(competitionId, OrganizerId);
                Assert.True(closed.Success, closed.Message);
            }
            return (competitionId, startDate);
        }

        public async Task<(int CompetitionId, DateTime StartDate)> CreateAndRegisterIndividualTournamentAsync()
        {
            var now = DateTime.UtcNow;
            var registrationEnd = now.AddSeconds(20);
            var startDate = now.AddSeconds(22);
            int competitionId;
            await using (var context = CreateContext())
            {
                var service = new CompetitionService(new CompetitionRepository(context), new DebateFormatRepository(context),
                    new UserRepository(context), new CompetitionRegistrationRepository(context), new CompetitionTeamRepository(context));
                var created = await service.CreateAsync(OrganizerId, new CreateCompetitionRequest
                {
                    Title = $"ADPP SQL test {_token} full workflow",
                    CompetitionType = "INDIVIDUAL", FormatId = Format1v1Id, MaxParticipants = 2,
                    RegistrationStart = now.AddMinutes(-1), RegistrationEnd = registrationEnd,
                    StartDate = startDate
                });
                Assert.True(created.Success, created.Message);
                competitionId = created.Data!.CompetitionId;
                _competitionIds.Add(competitionId);
                var opened = await service.OpenRegistrationAsync(competitionId, OrganizerId);
                Assert.True(opened.Success, opened.Message);
            }
            await using (var context = CreateContext())
            {
                var registration = new CompetitionRegistrationService(new CompetitionRegistrationRepository(context),
                    new CompetitionRepository(context));
                var first = await registration.RegisterAsync(competitionId, Player1Id);
                var second = await registration.RegisterAsync(competitionId, Player2Id);
                Assert.True(first.Success, first.Message);
                Assert.True(second.Success, second.Message);
                Assert.True((await registration.ApproveAsync(competitionId, first.Data!.RegistrationId, OrganizerId)).Success);
                Assert.True((await registration.ApproveAsync(competitionId, second.Data!.RegistrationId, OrganizerId)).Success);
            }
            await using (var context = CreateContext())
            {
                var service = new CompetitionService(new CompetitionRepository(context), new DebateFormatRepository(context),
                    new UserRepository(context), new CompetitionRegistrationRepository(context), new CompetitionTeamRepository(context));
                var closed = await service.CloseRegistrationAsync(competitionId, OrganizerId);
                Assert.True(closed.Success, closed.Message);
            }
            return (competitionId, startDate);
        }

        public async Task StartTournamentAsync(int competitionId)
        {
            await using var context = CreateContext();
            var service = new CompetitionService(new CompetitionRepository(context), new DebateFormatRepository(context),
                new UserRepository(context), new CompetitionRegistrationRepository(context), new CompetitionTeamRepository(context));
            var started = await service.StartCompetitionAsync(competitionId, OrganizerId);
            Assert.True(started.Success, started.Message);
        }

        public async Task<FinalizeMatchRequest> PlayAndFinalizeAsync(int competitionId, int matchId, bool liveAi = false, bool finalize = true)
        {
            await using (var assignContext = CreateContext())
            {
                var assigned = await new CompetitionTournamentService(assignContext)
                    .AssignJudgeAsync(competitionId, matchId, OrganizerId, JudgeId);
                Assert.True(assigned.Success, assigned.Message);
            }
            int sessionId;
            await using (var prepareContext = CreateContext())
            {
                var prepared = await CreateBridge(prepareContext).PrepareMatchDebateAsync(OrganizerId, matchId, TopicId);
                Assert.True(prepared.Success, prepared.Message);
                sessionId = prepared.Data!.SessionId;
            }
            await using (var startContext = CreateContext())
            {
                var started = await CreateDebateService(startContext).StartDebateSessionAsync(JudgeId, sessionId);
                Assert.True(started.Success, started.Message);
            }
            List<int> speakerOrder;
            int roundCount;
            await using (var setup = CreateContext())
            {
                var participants = await setup.DebateParticipants.Where(p => p.DebateSessionId == sessionId).ToListAsync();
                var pro = participants.Where(p => p.Side == DebateSide.PRO).OrderBy(p => p.ParticipantId).ToList();
                var con = participants.Where(p => p.Side == DebateSide.CON).OrderBy(p => p.ParticipantId).ToList();
                Assert.Equal(pro.Count, con.Count);
                speakerOrder = Enumerable.Range(0, participants.Count)
                    .Select(i => (i % 2 == 0 ? pro[i / 2] : con[i / 2]).UserId!.Value).ToList();
                roundCount = await setup.DebateRounds.CountAsync(r => r.DebateSessionId == sessionId);
            }
            for (var round = 0; round < roundCount; round++)
            {
                foreach (var userId in speakerOrder)
                {
                    await using var submitContext = CreateContext();
                    var finalTurn = round == roundCount - 1 && userId == speakerOrder.Last();
                    using var httpClient = liveAi && finalTurn ? new HttpClient
                    {
                        BaseAddress = new Uri(Environment.GetEnvironmentVariable("ADPP_AI_EVALUATOR_URL")!.TrimEnd('/') + "/"),
                        Timeout = TimeSpan.FromSeconds(120)
                    } : null;
                    var debate = httpClient == null ? CreateDebateService(submitContext)
                        : new DebateService(new DebateRepository(submitContext), new UserRepository(submitContext),
                            new AiEvaluatorClient(httpClient, NullLogger<AiEvaluatorClient>.Instance), NullLogger<DebateService>.Instance);
                    var content = liveAi
                        ? speakerOrder.IndexOf(userId) % 2 == 0
                            ? $"Round {round + 1}: I support the motion. A clear policy can improve access and accountability when its costs are measured, its safeguards are public, and people affected by it can give feedback. The opposing view overlooks these practical benefits."
                            : $"Round {round + 1}: I oppose the motion. The proposed policy may impose costs on people with fewer resources, and its promised benefits depend on assumptions that need evidence. A narrower approach with explicit safeguards would address the problem more fairly."
                        : $"Fixture round {round + 1} argument from {userId}";
                    var submitted = await debate.SubmitArgumentAsync(userId, sessionId,
                        new SubmitArgumentRequest { Content = content });
                    Assert.True(submitted.Success, submitted.Message);
                    if (finalTurn)
                        Assert.Equal(SessionStatus.Completed, submitted.Data!.Status);
                }
            }
            await using (var scoreContext = CreateContext())
            {
                var match = await scoreContext.CompetitionMatches.Include(m => m.Participants).SingleAsync(m => m.CompetitionMatchId == matchId);
                Assert.Equal("Evaluating", match.Status);
                if (!liveAi)
                {
                    scoreContext.AIJudgements.Add(new AIJudgement { DebateSessionId = sessionId,
                        SuggestedWinnerSide = "PRO", OverallScorePro = 8m, OverallScoreCon = 6m,
                        AIProvider = "fixture", AIModel = "fixture" });
                    await scoreContext.SaveChangesAsync();
                }
                else Assert.True(await scoreContext.AIJudgements.AnyAsync(j => j.DebateSessionId == sessionId),
                    "Live AI evaluator must persist an AIJudgement before human review.");
                var tournament = new CompetitionTournamentService(scoreContext);
                var review = await tournament.GetReviewAsync(competitionId, matchId, JudgeId);
                Assert.True(review.Success, review.Message);
                if (!liveAi) Assert.Equal("PRO", review.Data!.AiSuggestedWinnerSide);
                var criteria = await scoreContext.DebateCriteria.AsNoTracking().Where(c => c.IsActive).ToListAsync();
                var scores = match.Participants.SelectMany(p => criteria.Select(c => new ScoreInput(
                    p.MatchParticipantId, c.CriteriaId, p.Side == "PRO" ? Math.Min(2m, c.MaxScore) : Math.Min(1m, c.MaxScore), "fixture score"))).ToList();
                var winnerId = match.Participants.Single(p => p.Side == "PRO").MatchParticipantId;
                var decision = new FinalizeMatchRequest(scores, winnerId, "fixture decision");
                if (!finalize) return decision;
                var finalized = await tournament.FinalizeMatchAsync(competitionId, matchId, JudgeId, decision);
                Assert.True(finalized.Success, finalized.Message);
                var duplicate = await tournament.FinalizeMatchAsync(competitionId, matchId, JudgeId,
                    new FinalizeMatchRequest(scores, winnerId, "duplicate"));
                Assert.False(duplicate.Success);
                return decision;
            }
        }

        public async Task<int> PrepareAsync(MatchFixture match)
        {
            await using var context = CreateContext();
            var result = await CreateBridge(context).PrepareMatchDebateAsync(OrganizerId, match.MatchId, TopicId);
            Assert.True(result.Success, result.Message);
            return result.Data!.SessionId;
        }

        public async Task<int> CreateStandaloneSessionAsync()
        {
            await using var context = CreateContext();
            var session = new DebateSession
            {
                TopicId = TopicId,
                FormatId = Format1v1Id,
                CreatedBy = OrganizerId,
                Status = SessionStatus.Waiting,
                CreatedAt = DateTime.UtcNow
            };
            session.Participants.Add(new DebateParticipant
            {
                UserId = Player1Id, ParticipantType = ParticipantType.USER, Side = DebateSide.PRO, JoinedAt = DateTime.UtcNow
            });
            session.Participants.Add(new DebateParticipant
            {
                UserId = Player2Id, ParticipantType = ParticipantType.USER, Side = DebateSide.CON, JoinedAt = DateTime.UtcNow
            });
            foreach (var round in CreateRounds())
            {
                session.DebateRounds.Add(round);
            }
            context.DebateSessions.Add(session);
            await context.SaveChangesAsync();
            _standaloneSessionIds.Add(session.DebateSessionId);
            return session.DebateSessionId;
        }

        private static IEnumerable<DebateRound> CreateRounds()
        {
            var types = new[] { RoundType.OPENING, RoundType.REBUTTAL, RoundType.CLOSING };
            return types.Select((roundType, index) => new DebateRound
            {
                RoundNumber = index + 1,
                RoundType = roundType,
                CreatedAt = DateTime.UtcNow
            });
        }

        public async ValueTask DisposeAsync()
        {
            if (_userIds.Count == 0 && _competitionIds.Count == 0 && _roundIds.Count == 0 &&
                _matchIds.Count == 0 && _teamIds.Count == 0 && _createdFormatIds.Count == 0 &&
                _standaloneSessionIds.Count == 0)
            {
                return;
            }

            var ownedUserIds = _userIds.Distinct().ToList();
            var ownedCompetitionIds = _competitionIds.Distinct().ToList();
            var ownedRoundIds = _roundIds.Distinct().ToList();
            var ownedMatchIds = _matchIds.Distinct().ToList();
            var ownedTeamIds = _teamIds.Distinct().ToList();
            var ownedFormatIds = _createdFormatIds.Distinct().ToList();
            var ownedStandaloneSessionIds = _standaloneSessionIds.Distinct().ToList();
            var sessionIds = new List<int>();
            var roundIds = new List<int>();

            await using var context = CreateContext();
            await using var transaction = await context.Database.BeginTransactionAsync(IsolationLevel.ReadCommitted);
            try
            {
                ownedRoundIds.AddRange(await context.CompetitionRounds.Where(r => ownedCompetitionIds.Contains(r.CompetitionId))
                    .Select(r => r.CompetitionRoundId).ToListAsync());
                ownedMatchIds.AddRange(await context.CompetitionMatches.Where(m => ownedCompetitionIds.Contains(m.CompetitionId))
                    .Select(m => m.CompetitionMatchId).ToListAsync());
                ownedTeamIds.AddRange(await context.CompetitionTeams.Where(t => ownedCompetitionIds.Contains(t.CompetitionId))
                    .Select(t => t.TeamId).ToListAsync());
                // The organizer is a unique fixture-owned user. This also finds a DebateSession
                // left behind by a failed Prepare before the match link was committed.
                sessionIds = await context.DebateSessions
                    .Where(session => session.CreatedBy == OrganizerId)
                    .Select(session => session.DebateSessionId)
                    .ToListAsync();
                var linkedSessionIds = await context.CompetitionMatches
                    .Where(match => ownedMatchIds.Contains(match.CompetitionMatchId) && match.DebateSessionId.HasValue)
                    .Select(match => match.DebateSessionId!.Value)
                    .ToListAsync();
                sessionIds.AddRange(linkedSessionIds);
                sessionIds.AddRange(ownedStandaloneSessionIds);
                sessionIds = sessionIds.Distinct().ToList();
                roundIds = await context.DebateRounds.Where(round => sessionIds.Contains(round.DebateSessionId))
                    .Select(round => round.RoundId).ToListAsync();

                context.Arguments.RemoveRange(await context.Arguments.Where(argument => roundIds.Contains(argument.RoundId)).ToListAsync());
                await context.SaveChangesAsync();

                context.AIJudgements.RemoveRange(await context.AIJudgements.Where(judgement => sessionIds.Contains(judgement.DebateSessionId)).ToListAsync());
                await context.SaveChangesAsync();

                context.DebateParticipants.RemoveRange(await context.DebateParticipants.Where(participant => sessionIds.Contains(participant.DebateSessionId)).ToListAsync());
                await context.SaveChangesAsync();

                context.DebateRounds.RemoveRange(await context.DebateRounds.Where(round => sessionIds.Contains(round.DebateSessionId)).ToListAsync());
                await context.SaveChangesAsync();

                if (ownedMatchIds.Count > 0)
                {
                    await context.CompetitionMatches.Where(match => ownedMatchIds.Contains(match.CompetitionMatchId))
                        .ExecuteUpdateAsync(setters => setters.SetProperty(match => match.DebateSessionId, (int?)null)
                            .SetProperty(match => match.NextMatchId, (int?)null));
                }

                context.DebateSessions.RemoveRange(await context.DebateSessions.Where(session => sessionIds.Contains(session.DebateSessionId)).ToListAsync());
                context.JudgeScores.RemoveRange(await context.JudgeScores.Where(score => ownedMatchIds.Contains(score.CompetitionMatchId)).ToListAsync());
                context.MatchParticipants.RemoveRange(await context.MatchParticipants.Where(participant => ownedMatchIds.Contains(participant.CompetitionMatchId)).ToListAsync());
                context.CompetitionMatches.RemoveRange(await context.CompetitionMatches.Where(match => ownedMatchIds.Contains(match.CompetitionMatchId)).ToListAsync());
                await context.SaveChangesAsync();

                context.CompetitionTeamRequests.RemoveRange(await context.CompetitionTeamRequests
                    .Where(request => ownedTeamIds.Contains(request.TeamId)).ToListAsync());
                context.CompetitionRegistrations.RemoveRange(await context.CompetitionRegistrations
                    .Where(registration => ownedCompetitionIds.Contains(registration.CompetitionId)).ToListAsync());
                context.CompetitionJudges.RemoveRange(await context.CompetitionJudges
                    .Where(judge => ownedCompetitionIds.Contains(judge.CompetitionId)).ToListAsync());
                await context.SaveChangesAsync();

                if (ownedTeamIds.Count > 0)
                {
                    context.CompetitionTeamMembers.RemoveRange(await context.CompetitionTeamMembers.Where(member => ownedTeamIds.Contains(member.TeamId)).ToListAsync());
                    context.CompetitionTeams.RemoveRange(await context.CompetitionTeams.Where(team => ownedTeamIds.Contains(team.TeamId)).ToListAsync());
                }
                context.CompetitionRounds.RemoveRange(await context.CompetitionRounds.Where(round => ownedRoundIds.Contains(round.CompetitionRoundId)).ToListAsync());
                context.Competitions.RemoveRange(await context.Competitions.Where(competition => ownedCompetitionIds.Contains(competition.CompetitionId)).ToListAsync());
                await context.SaveChangesAsync();

                if (ownedFormatIds.Count > 0)
                {
                    context.DebateFormats.RemoveRange(await context.DebateFormats
                        .Where(format => ownedFormatIds.Contains(format.FormatId)).ToListAsync());
                    await context.SaveChangesAsync();
                }

                context.UserRoles.RemoveRange(await context.UserRoles.Where(role => ownedUserIds.Contains(role.UserId)).ToListAsync());
                await context.SaveChangesAsync();
                context.Users.RemoveRange(await context.Users.Where(user => ownedUserIds.Contains(user.UserId)).ToListAsync());
                await context.SaveChangesAsync();

                var hasRemainingOwnedData =
                    await context.Users.AnyAsync(user => ownedUserIds.Contains(user.UserId)) ||
                    await context.Competitions.AnyAsync(competition => ownedCompetitionIds.Contains(competition.CompetitionId)) ||
                    await context.CompetitionRounds.AnyAsync(round => ownedRoundIds.Contains(round.CompetitionRoundId)) ||
                    await context.CompetitionMatches.AnyAsync(match => ownedMatchIds.Contains(match.CompetitionMatchId)) ||
                    await context.CompetitionTeams.AnyAsync(team => ownedTeamIds.Contains(team.TeamId)) ||
                    await context.DebateSessions.AnyAsync(session => sessionIds.Contains(session.DebateSessionId)) ||
                    await context.DebateRounds.AnyAsync(round => roundIds.Contains(round.RoundId)) ||
                    await context.Arguments.AnyAsync(argument => roundIds.Contains(argument.RoundId)) ||
                    await context.DebateParticipants.AnyAsync(participant => sessionIds.Contains(participant.DebateSessionId)) ||
                    await context.AIJudgements.AnyAsync(judgement => sessionIds.Contains(judgement.DebateSessionId)) ||
                    await context.JudgeScores.AnyAsync(score => ownedMatchIds.Contains(score.CompetitionMatchId)) ||
                    await context.MatchParticipants.AnyAsync(participant => ownedMatchIds.Contains(participant.CompetitionMatchId)) ||
                    await context.CompetitionTeamMembers.AnyAsync(member => ownedTeamIds.Contains(member.TeamId)) ||
                    await context.CompetitionTeamRequests.AnyAsync(request => ownedTeamIds.Contains(request.TeamId)) ||
                    await context.CompetitionRegistrations.AnyAsync(registration => ownedCompetitionIds.Contains(registration.CompetitionId)) ||
                    await context.CompetitionJudges.AnyAsync(judge => ownedCompetitionIds.Contains(judge.CompetitionId)) ||
                    await context.UserRoles.AnyAsync(role => ownedUserIds.Contains(role.UserId)) ||
                    await context.DebateFormats.AnyAsync(format => ownedFormatIds.Contains(format.FormatId));
                if (hasRemainingOwnedData)
                {
                    throw new InvalidOperationException("Fixture cleanup verification found rows that still belong to this fixture.");
                }

                await transaction.CommitAsync();
            }
            catch (Exception exception)
            {
                await transaction.RollbackAsync();
                throw new InvalidOperationException($"Cleanup failed for SQL Server fixture adpp-sql-it-{_token}; owned UserIds=[{string.Join(',', ownedUserIds)}], CompetitionIds=[{string.Join(',', ownedCompetitionIds)}], RoundIds=[{string.Join(',', ownedRoundIds)}], MatchIds=[{string.Join(',', ownedMatchIds)}], TeamIds=[{string.Join(',', ownedTeamIds)}], SessionIds=[{string.Join(',', sessionIds)}], DebateRoundIds=[{string.Join(',', roundIds)}], FormatIds=[{string.Join(',', ownedFormatIds)}]. No unrelated records were deleted.", exception);
            }
        }
    }

    private sealed record MatchFixture(int MatchId, int CompetitionId, int RoundId, bool IsTeam);

    private sealed class BumpMatchRowVersionAfterInsert : SaveChangesInterceptor
    {
        private readonly string _connectionString;
        private readonly int _matchId;
        private int _triggered;

        public BumpMatchRowVersionAfterInsert(string connectionString, int matchId)
        {
            _connectionString = connectionString;
            _matchId = matchId;
        }

        public bool WasTriggered => Volatile.Read(ref _triggered) == 1;

        public override async ValueTask<int> SavedChangesAsync(
            SaveChangesCompletedEventData eventData,
            int result,
            CancellationToken cancellationToken = default)
        {
            if (Interlocked.CompareExchange(ref _triggered, 1, 0) == 0)
            {
                var options = new DbContextOptionsBuilder<SystemDbContext>()
                    .UseSqlServer(_connectionString)
                    .Options;
                await using var competingContext = new SystemDbContext(options);
                var match = await competingContext.CompetitionMatches.SingleAsync(m => m.CompetitionMatchId == _matchId, cancellationToken);
                match.UpdatedAt = DateTime.UtcNow.AddSeconds(1);
                await competingContext.SaveChangesAsync(cancellationToken);
            }
            return result;
        }
    }
}
