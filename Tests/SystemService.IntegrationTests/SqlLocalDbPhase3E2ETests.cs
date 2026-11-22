using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Data.SqlClient;
using Microsoft.EntityFrameworkCore;
using SystemService.BLL.DTOs.AI;
using SystemService.BLL.DTOs.Competition.Tournament;
using SystemService.BLL.Services.AI.Interfaces;
using SystemService.BLL.Services.Competition;
using SystemService.BLL.Services.Competition.Implementations;
using SystemService.BLL.Services.Debate.Implementations;
using SystemService.DAL.Context;
using SystemService.DAL.Entities.Competition;
using SystemService.DAL.Entities.Debate;
using SystemService.DAL.Entities.Debate.Enums;
using SystemService.DAL.Entities.Identity;
using SystemService.DAL.Repositories.Debate.Implementations;
using SystemService.DAL.Repositories.Identity.Implementations;
using Xunit;

namespace SystemService.IntegrationTests
{
    public sealed class LocalDbFactAttribute : FactAttribute
    {
        public LocalDbFactAttribute()
        {
            if (!OperatingSystem.IsWindows())
            {
                Skip = "SQL Server LocalDB is only available on Windows.";
            }
        }
    }

    public class SqlLocalDbPhase3E2ETests
    {
        private static string BuildLocalDbConnStr(string dbName)
            => $"Server=(localdb)\\MSSQLLocalDB;Database={dbName};Trusted_Connection=True;TrustServerCertificate=True;MultipleActiveResultSets=True;";

        private sealed class FakeScale1To5AiClient : IAiEvaluatorClient
        {
            public int ProScore { get; set; } = 4;
            public int ConScore { get; set; } = 3;

            public Task<EvaluateArgumentResponse?> EvaluateArgumentAsync(EvaluateArgumentRequest req, CancellationToken ct = default)
                => Task.FromResult<EvaluateArgumentResponse?>(null);

            public Task<EvaluateRoundResponse?> EvaluateRoundAsync(EvaluateRoundRequest req, CancellationToken ct = default)
            {
                int s = req.Side == "pro" ? ProScore : ConScore;
                return Task.FromResult<EvaluateRoundResponse?>(new EvaluateRoundResponse(
                    Stage: req.Stage,
                    RoundScore: s * 2.0m,
                    Criteria: new List<CriterionScoreDto>
                    {
                        new("Logic", s, "Logic", "LOGIC"),
                        new("Evidence", s, "Evidence", "EVIDENCE"),
                        new("Relevance", s, "Relevance", "RELEVANCE"),
                        new("Structure", s, "Structure", "STRUCTURE"),
                        new("Persuasiveness", s, "Persuasiveness", "PERSUASIVENESS")
                    },
                    ConsistencyNote: "Consistent",
                    Strengths: new List<string> { "Clear" },
                    Weaknesses: new List<string>(),
                    Suggestions: new List<string>()
                ));
            }

            public Task<EvaluateSessionResponse?> EvaluateSessionAsync(EvaluateSessionRequest req, CancellationToken ct = default)
            {
                decimal overall = (req.Side == "pro" ? ProScore : ConScore) * 2.0m;
                return Task.FromResult<EvaluateSessionResponse?>(new EvaluateSessionResponse(
                    OverallScore: overall,
                    StageBreakdown: new Dictionary<string, decimal> { { "opening", overall }, { "rebuttal", overall }, { "closing", overall } },
                    ProgressTrend: "Consistent",
                    OverallStrengths: new List<string> { "Good" },
                    OverallWeaknesses: new List<string>(),
                    OverallSuggestions: new List<string>()
                ));
            }

            public Task<CoachingResultDto?> CoachArgumentAsync(ArgumentCoachingRequest req, CancellationToken ct = default)
                => Task.FromResult<CoachingResultDto?>(null);

            public Task<CoachingResultDto?> CoachRoundAsync(RoundCoachingRequest req, CancellationToken ct = default)
                => Task.FromResult<CoachingResultDto?>(null);
        }

        private static async Task SeedCriteriaAsync(SystemDbContext ctx)
        {
            if (await ctx.DebateCriteria.AnyAsync()) return;
            ctx.DebateCriteria.AddRange(
                new DebateCriteria { CriterionCode = "LOGIC", CriteriaName = "Logic", Weight = 1.0m, IsActive = true },
                new DebateCriteria { CriterionCode = "EVIDENCE", CriteriaName = "Evidence", Weight = 1.0m, IsActive = true },
                new DebateCriteria { CriterionCode = "RELEVANCE", CriteriaName = "Relevance", Weight = 1.0m, IsActive = true },
                new DebateCriteria { CriterionCode = "STRUCTURE", CriteriaName = "Structure", Weight = 1.0m, IsActive = true },
                new DebateCriteria { CriterionCode = "PERSUASIVENESS", CriteriaName = "Persuasiveness", Weight = 1.0m, IsActive = true }
            );
            await ctx.SaveChangesAsync();
        }

        [LocalDbFact]
        public async Task LocalDb_NewDatabase_DebateScoreWeight_DefaultMaxScore_Is5()
        {
            var dbName = $"ADPP_Phase3_Schema_{Guid.NewGuid():N}";
            var options = new DbContextOptionsBuilder<SystemDbContext>()
                .UseSqlServer(BuildLocalDbConnStr(dbName))
                .Options;

            await using var ctx = new SystemDbContext(options);
            try
            {
                await ctx.Database.EnsureCreatedAsync();
                await SeedCriteriaAsync(ctx);

                var criteria = await ctx.DebateCriteria.AsNoTracking().ToListAsync();
                Assert.Equal(5, criteria.Count);
                Assert.All(criteria, c => Assert.Equal(5.00m, c.MaxScore));
            }
            finally
            {
                await ctx.Database.EnsureDeletedAsync();
            }
        }

        [LocalDbFact]
        public async Task LocalDb_Phase3_1v1_Evaluate_Review_Accept_Override_And_Champion()
        {
            var dbName = $"ADPP_Phase3_1v1_{Guid.NewGuid():N}";
            var options = new DbContextOptionsBuilder<SystemDbContext>()
                .UseSqlServer(BuildLocalDbConnStr(dbName))
                .Options;

            await using var ctx = new SystemDbContext(options);
            try
            {
                await ctx.Database.EnsureCreatedAsync();
                await SeedCriteriaAsync(ctx);

                var org = new User { FullName = "Org", Email = $"org_{Guid.NewGuid():N}@test.com", PasswordHash = "h" };
                var p1 = new User { FullName = "P1", Email = $"p1_{Guid.NewGuid():N}@test.com", PasswordHash = "h" };
                var p2 = new User { FullName = "P2", Email = $"p2_{Guid.NewGuid():N}@test.com", PasswordHash = "h" };
                var p3 = new User { FullName = "P3", Email = $"p3_{Guid.NewGuid():N}@test.com", PasswordHash = "h" };
                ctx.Users.AddRange(org, p1, p2, p3);
                var format = new DebateFormat { FormatName = "1 vs 1", MaxParticipants = 2, TotalRounds = 3, RoundDurationSeconds = 180, IsActive = true };
                ctx.DebateFormats.Add(format);
                await ctx.SaveChangesAsync();

                var comp = new Competition { Title = "SQL 1v1", CompetitionType = "INDIVIDUAL", CreatedBy = org.UserId, FormatId = format.FormatId, Status = "Ongoing", StartDate = DateTime.UtcNow };
                ctx.Competitions.Add(comp);
                await ctx.SaveChangesAsync();

                var r1 = new CompetitionRound { CompetitionId = comp.CompetitionId, RoundNumber = 1, RoundName = "Semi", Status = "Ongoing" };
                var r2 = new CompetitionRound { CompetitionId = comp.CompetitionId, RoundNumber = 2, RoundName = "Final", Status = "Pending" };
                ctx.CompetitionRounds.AddRange(r1, r2);
                await ctx.SaveChangesAsync();

                var finalMatch = new CompetitionMatch { CompetitionId = comp.CompetitionId, CompetitionRoundId = r2.CompetitionRoundId, MatchNumber = 1, BracketPosition = 1, Status = "Scheduled" };
                ctx.CompetitionMatches.Add(finalMatch);
                await ctx.SaveChangesAsync();

                ctx.MatchParticipants.Add(new MatchParticipant { CompetitionMatchId = finalMatch.CompetitionMatchId, UserId = p3.UserId, Side = "CON", SeedNumber = 2 });

                var semiMatch = new CompetitionMatch { CompetitionId = comp.CompetitionId, CompetitionRoundId = r1.CompetitionRoundId, MatchNumber = 1, BracketPosition = 1, NextMatchId = finalMatch.CompetitionMatchId, Status = "Evaluating", EvaluationStatus = "Pending" };
                ctx.CompetitionMatches.Add(semiMatch);
                await ctx.SaveChangesAsync();

                ctx.MatchParticipants.AddRange(
                    new MatchParticipant { CompetitionMatchId = semiMatch.CompetitionMatchId, UserId = p1.UserId, Side = "PRO", SeedNumber = 1 },
                    new MatchParticipant { CompetitionMatchId = semiMatch.CompetitionMatchId, UserId = p2.UserId, Side = "CON", SeedNumber = 4 }
                );

                var topic = new Topic { Title = "Topic", Description = "Motion", Difficulty = "Easy" };
                ctx.Topics.Add(topic);
                await ctx.SaveChangesAsync();

                var semiSession = new DebateSession { TopicId = topic.TopicId, FormatId = format.FormatId, CreatedBy = org.UserId, Status = SessionStatus.Completed, StartTime = DateTime.UtcNow.AddMinutes(-20), EndTime = DateTime.UtcNow };
                ctx.DebateSessions.Add(semiSession);
                await ctx.SaveChangesAsync();
                semiMatch.DebateSessionId = semiSession.DebateSessionId;

                var dp1 = new DebateParticipant { DebateSessionId = semiSession.DebateSessionId, UserId = p1.UserId, Side = DebateSide.PRO };
                var dp2 = new DebateParticipant { DebateSessionId = semiSession.DebateSessionId, UserId = p2.UserId, Side = DebateSide.CON };
                ctx.DebateParticipants.AddRange(dp1, dp2);
                for (int r = 1; r <= 3; r++)
                {
                    var dr = new DebateRound { DebateSessionId = semiSession.DebateSessionId, RoundNumber = r, RoundType = r == 1 ? RoundType.OPENING : (r == 2 ? RoundType.REBUTTAL : RoundType.CLOSING), StartTime = DateTime.UtcNow.AddMinutes(-10), EndTime = DateTime.UtcNow };
                    ctx.DebateRounds.Add(dr);
                    await ctx.SaveChangesAsync();
                    ctx.Arguments.AddRange(
                        new Argument { RoundId = dr.RoundId, ParticipantId = dp1.ParticipantId, Content = $"PRO r{r}" },
                        new Argument { RoundId = dr.RoundId, ParticipantId = dp2.ParticipantId, Content = $"CON r{r}" }
                    );
                }
                await ctx.SaveChangesAsync();

                var debateService = new DebateService(new DebateRepository(ctx), new UserRepository(ctx), new FakeScale1To5AiClient { ProScore = 4, ConScore = 3 });
                var evalRes = await debateService.EvaluateSessionAsync(p1.UserId, semiSession.DebateSessionId);
                Assert.True(evalRes.Success, evalRes.Message);

                var tournamentService = new CompetitionTournamentService(ctx);
                var review = await tournamentService.GetReviewAsync(comp.CompetitionId, semiMatch.CompetitionMatchId, org.UserId);
                Assert.True(review.Success, review.Message);
                Assert.Equal(30, review.Data!.RoundRubrics!.Count);
                Assert.All(review.Data.RoundRubrics, rr => Assert.InRange(rr.AiScore, 1m, 5m));

                var acceptRes = await tournamentService.FinalizeMatchAsync(comp.CompetitionId, semiMatch.CompetitionMatchId, org.UserId, new FinalizeMatchRequest(decisionType: "ACCEPT"));
                Assert.True(acceptRes.Success, acceptRes.Message);

                // Final match: AI proposes PRO (p1), BTC OVERRIDES to CON (p3)
                var finalSession = new DebateSession { TopicId = topic.TopicId, FormatId = format.FormatId, CreatedBy = org.UserId, Status = SessionStatus.Completed, StartTime = DateTime.UtcNow.AddMinutes(-20), EndTime = DateTime.UtcNow };
                ctx.DebateSessions.Add(finalSession);
                await ctx.SaveChangesAsync();

                var reloadedFinal = await ctx.CompetitionMatches.Include(m => m.Participants).SingleAsync(m => m.CompetitionMatchId == finalMatch.CompetitionMatchId);
                Assert.Equal("Ready", reloadedFinal.Status);
                reloadedFinal.DebateSessionId = finalSession.DebateSessionId;
                reloadedFinal.Status = "Evaluating";
                await ctx.SaveChangesAsync();

                var fdp1 = new DebateParticipant { DebateSessionId = finalSession.DebateSessionId, UserId = p1.UserId, Side = DebateSide.PRO };
                var fdp3 = new DebateParticipant { DebateSessionId = finalSession.DebateSessionId, UserId = p3.UserId, Side = DebateSide.CON };
                ctx.DebateParticipants.AddRange(fdp1, fdp3);
                for (int r = 1; r <= 3; r++)
                {
                    var dr = new DebateRound { DebateSessionId = finalSession.DebateSessionId, RoundNumber = r, RoundType = r == 1 ? RoundType.OPENING : (r == 2 ? RoundType.REBUTTAL : RoundType.CLOSING), StartTime = DateTime.UtcNow.AddMinutes(-10), EndTime = DateTime.UtcNow };
                    ctx.DebateRounds.Add(dr);
                    await ctx.SaveChangesAsync();
                    ctx.Arguments.AddRange(
                        new Argument { RoundId = dr.RoundId, ParticipantId = fdp1.ParticipantId, Content = $"Final PRO r{r}" },
                        new Argument { RoundId = dr.RoundId, ParticipantId = fdp3.ParticipantId, Content = $"Final CON r{r}" }
                    );
                }
                await ctx.SaveChangesAsync();

                var finalEval = await debateService.EvaluateSessionAsync(p1.UserId, finalSession.DebateSessionId);
                Assert.True(finalEval.Success, finalEval.Message);

                var criteria = await ctx.DebateCriteria.Where(c => c.IsActive).ToListAsync();
                var finalRounds = await ctx.DebateRounds.Where(r => r.DebateSessionId == finalSession.DebateSessionId).ToListAsync();
                var proMpId = reloadedFinal.Participants.Single(p => p.Side == "PRO").MatchParticipantId;
                var conMpId = reloadedFinal.Participants.Single(p => p.Side == "CON").MatchParticipantId;

                var overrideScores = new List<RoundScoreInput>();
                foreach (var dr in finalRounds)
                {
                    foreach (var c in criteria)
                    {
                        overrideScores.Add(new RoundScoreInput(dr.RoundId, proMpId, c.CriteriaId, 2.0m));
                        overrideScores.Add(new RoundScoreInput(dr.RoundId, conMpId, c.CriteriaId, 5.0m));
                    }
                }

                var overrideRes = await tournamentService.FinalizeMatchAsync(
                    comp.CompetitionId,
                    finalMatch.CompetitionMatchId,
                    org.UserId,
                    new FinalizeMatchRequest(decisionType: "OVERRIDE", decisionReason: "CON stronger closing", scores: overrideScores));
                Assert.True(overrideRes.Success, overrideRes.Message);

                var bracket = await tournamentService.GetBracketAsync(comp.CompetitionId, CancellationToken.None, org.UserId);
                Assert.True(bracket.Success);
                Assert.Equal(p3.UserId, bracket.Data!.ChampionUserId);
                Assert.Equal("Completed", (await ctx.Competitions.FindAsync(comp.CompetitionId))!.Status);
            }
            finally
            {
                await ctx.Database.EnsureDeletedAsync();
            }
        }

        [LocalDbFact]
        public async Task LocalDb_Phase3_2v2_Evaluate_Review_Accept_And_TeamChampion()
        {
            var dbName = $"ADPP_Phase3_2v2_{Guid.NewGuid():N}";
            var options = new DbContextOptionsBuilder<SystemDbContext>()
                .UseSqlServer(BuildLocalDbConnStr(dbName))
                .Options;

            await using var ctx = new SystemDbContext(options);
            try
            {
                await ctx.Database.EnsureCreatedAsync();
                await SeedCriteriaAsync(ctx);

                var org = new User { FullName = "Org", Email = $"org2v2_{Guid.NewGuid():N}@test.com", PasswordHash = "h" };
                var u1 = new User { FullName = "U1", Email = $"u1_{Guid.NewGuid():N}@test.com", PasswordHash = "h" };
                var u2 = new User { FullName = "U2", Email = $"u2_{Guid.NewGuid():N}@test.com", PasswordHash = "h" };
                var u3 = new User { FullName = "U3", Email = $"u3_{Guid.NewGuid():N}@test.com", PasswordHash = "h" };
                var u4 = new User { FullName = "U4", Email = $"u4_{Guid.NewGuid():N}@test.com", PasswordHash = "h" };
                ctx.Users.AddRange(org, u1, u2, u3, u4);
                var format = new DebateFormat { FormatName = "2 vs 2", MaxParticipants = 4, TotalRounds = 3, RoundDurationSeconds = 180, IsActive = true };
                ctx.DebateFormats.Add(format);
                await ctx.SaveChangesAsync();

                var comp = new Competition { Title = "SQL 2v2", CompetitionType = "TEAM", CreatedBy = org.UserId, FormatId = format.FormatId, Status = "Ongoing", StartDate = DateTime.UtcNow };
                ctx.Competitions.Add(comp);
                await ctx.SaveChangesAsync();

                var teamA = new CompetitionTeam { CompetitionId = comp.CompetitionId, TeamName = "Alpha", CaptainUserId = u1.UserId, Status = "Active" };
                var teamB = new CompetitionTeam { CompetitionId = comp.CompetitionId, TeamName = "Beta", CaptainUserId = u3.UserId, Status = "Active" };
                ctx.CompetitionTeams.AddRange(teamA, teamB);
                await ctx.SaveChangesAsync();

                ctx.CompetitionTeamMembers.AddRange(
                    new CompetitionTeamMember { TeamId = teamA.TeamId, UserId = u2.UserId },
                    new CompetitionTeamMember { TeamId = teamB.TeamId, UserId = u4.UserId }
                );

                var r1 = new CompetitionRound { CompetitionId = comp.CompetitionId, RoundNumber = 1, RoundName = "Final", Status = "Ongoing" };
                ctx.CompetitionRounds.Add(r1);
                await ctx.SaveChangesAsync();

                var finalMatch = new CompetitionMatch { CompetitionId = comp.CompetitionId, CompetitionRoundId = r1.CompetitionRoundId, MatchNumber = 1, BracketPosition = 1, Status = "Evaluating", EvaluationStatus = "Pending" };
                ctx.CompetitionMatches.Add(finalMatch);
                await ctx.SaveChangesAsync();

                ctx.MatchParticipants.AddRange(
                    new MatchParticipant { CompetitionMatchId = finalMatch.CompetitionMatchId, TeamId = teamA.TeamId, Side = "PRO", SeedNumber = 1 },
                    new MatchParticipant { CompetitionMatchId = finalMatch.CompetitionMatchId, TeamId = teamB.TeamId, Side = "CON", SeedNumber = 2 }
                );

                var topic = new Topic { Title = "2v2 Topic", Description = "2v2 Motion", Difficulty = "Medium" };
                ctx.Topics.Add(topic);
                await ctx.SaveChangesAsync();

                var session = new DebateSession { TopicId = topic.TopicId, FormatId = format.FormatId, CreatedBy = org.UserId, Status = SessionStatus.Completed, StartTime = DateTime.UtcNow.AddMinutes(-20), EndTime = DateTime.UtcNow };
                ctx.DebateSessions.Add(session);
                await ctx.SaveChangesAsync();
                finalMatch.DebateSessionId = session.DebateSessionId;

                var dp1 = new DebateParticipant { DebateSessionId = session.DebateSessionId, UserId = u1.UserId, Side = DebateSide.PRO };
                var dp2 = new DebateParticipant { DebateSessionId = session.DebateSessionId, UserId = u2.UserId, Side = DebateSide.PRO };
                var dp3 = new DebateParticipant { DebateSessionId = session.DebateSessionId, UserId = u3.UserId, Side = DebateSide.CON };
                var dp4 = new DebateParticipant { DebateSessionId = session.DebateSessionId, UserId = u4.UserId, Side = DebateSide.CON };
                ctx.DebateParticipants.AddRange(dp1, dp2, dp3, dp4);

                for (int r = 1; r <= 3; r++)
                {
                    var dr = new DebateRound { DebateSessionId = session.DebateSessionId, RoundNumber = r, RoundType = r == 1 ? RoundType.OPENING : (r == 2 ? RoundType.REBUTTAL : RoundType.CLOSING), StartTime = DateTime.UtcNow.AddMinutes(-10), EndTime = DateTime.UtcNow };
                    ctx.DebateRounds.Add(dr);
                    await ctx.SaveChangesAsync();
                    ctx.Arguments.AddRange(
                        new Argument { RoundId = dr.RoundId, ParticipantId = dp1.ParticipantId, Content = $"A1 r{r}" },
                        new Argument { RoundId = dr.RoundId, ParticipantId = dp3.ParticipantId, Content = $"B1 r{r}" },
                        new Argument { RoundId = dr.RoundId, ParticipantId = dp2.ParticipantId, Content = $"A2 r{r}" },
                        new Argument { RoundId = dr.RoundId, ParticipantId = dp4.ParticipantId, Content = $"B2 r{r}" }
                    );
                }
                await ctx.SaveChangesAsync();

                var debateService = new DebateService(new DebateRepository(ctx), new UserRepository(ctx), new FakeScale1To5AiClient { ProScore = 5, ConScore = 3 });
                var evalRes = await debateService.EvaluateSessionAsync(u1.UserId, session.DebateSessionId);
                Assert.True(evalRes.Success, evalRes.Message);

                var tournamentService = new CompetitionTournamentService(ctx);
                var acceptRes = await tournamentService.FinalizeMatchAsync(comp.CompetitionId, finalMatch.CompetitionMatchId, org.UserId, new FinalizeMatchRequest(decisionType: "ACCEPT"));
                Assert.True(acceptRes.Success, acceptRes.Message);

                var bracket = await tournamentService.GetBracketAsync(comp.CompetitionId, CancellationToken.None, org.UserId);
                Assert.True(bracket.Success);
                Assert.Equal(teamA.TeamId, bracket.Data!.ChampionTeamId);
                Assert.Null(bracket.Data.ChampionUserId);
                Assert.Equal("Completed", (await ctx.Competitions.FindAsync(comp.CompetitionId))!.Status);
            }
            finally
            {
                await ctx.Database.EnsureDeletedAsync();
            }
        }
    }
}
