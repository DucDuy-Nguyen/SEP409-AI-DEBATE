using System;
using System.Collections.Generic;
using System.Linq;
using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Data.Sqlite;
using Microsoft.EntityFrameworkCore;
using SystemService.BLL.Common.Responses;
using SystemService.BLL.DTOs.AI;
using SystemService.BLL.DTOs.Competition.Tournament;
using SystemService.BLL.DTOs.Debate;
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
    public class Phase3AiEvaluationAndFinalizationTests : IDisposable
    {
        private readonly SqliteConnection _connection;
        private readonly DbContextOptions<SystemDbContext> _options;

        public Phase3AiEvaluationAndFinalizationTests()
        {
            _connection = new SqliteConnection("DataSource=:memory:");
            _connection.Open();

            _options = new DbContextOptionsBuilder<SystemDbContext>()
                .UseSqlite(_connection)
                .Options;

            using var context = CreateContext();
            context.Database.EnsureCreated();
            SeedCriteria(context);
        }

        private SystemDbContext CreateContext() => new TestSystemDbContext(_options);

        public class TestSystemDbContext : SystemDbContext
        {
            public TestSystemDbContext(DbContextOptions<SystemDbContext> options) : base(options) { }

            protected override void OnModelCreating(ModelBuilder modelBuilder)
            {
                base.OnModelCreating(modelBuilder);
                modelBuilder.Entity<CompetitionMatch>()
                    .Property(m => m.RowVersion)
                    .HasDefaultValue(new byte[] { 0, 0, 0, 1 });
            }
        }

        public void Dispose()
        {
            _connection.Dispose();
        }

        private static void SeedCriteria(SystemDbContext context)
        {
            if (context.DebateCriteria.Any()) return;

            context.DebateCriteria.AddRange(
                new DebateCriteria { CriteriaId = 1, CriterionCode = "LOGIC", CriteriaName = "Logic", MaxScore = 10.0m, Weight = 1.0m, IsActive = true },
                new DebateCriteria { CriteriaId = 2, CriterionCode = "EVIDENCE", CriteriaName = "Evidence", MaxScore = 10.0m, Weight = 1.0m, IsActive = true },
                new DebateCriteria { CriteriaId = 3, CriterionCode = "RELEVANCE", CriteriaName = "Relevance", MaxScore = 10.0m, Weight = 1.0m, IsActive = true },
                new DebateCriteria { CriteriaId = 4, CriterionCode = "STRUCTURE", CriteriaName = "Structure", MaxScore = 10.0m, Weight = 1.0m, IsActive = true },
                new DebateCriteria { CriteriaId = 5, CriterionCode = "PERSUASIVENESS", CriteriaName = "Persuasiveness", MaxScore = 10.0m, Weight = 1.0m, IsActive = true }
            );
            context.SaveChanges();
        }

        private class MockAiClient : IAiEvaluatorClient
        {
            public Func<EvaluateRoundRequest, EvaluateRoundResponse?>? RoundEvaluator { get; set; }
            public Func<EvaluateSessionRequest, EvaluateSessionResponse?>? SessionEvaluator { get; set; }
            public Exception? ExceptionToThrow { get; set; }

            public Task<EvaluateArgumentResponse?> EvaluateArgumentAsync(EvaluateArgumentRequest req, CancellationToken ct = default)
                => Task.FromResult<EvaluateArgumentResponse?>(null);

            public Task<EvaluateRoundResponse?> EvaluateRoundAsync(EvaluateRoundRequest req, CancellationToken ct = default)
            {
                if (ExceptionToThrow != null) throw ExceptionToThrow;
                if (RoundEvaluator != null) return Task.FromResult(RoundEvaluator(req));

                int baseScore = req.Side == "pro" ? 8 : 6;
                var res = new EvaluateRoundResponse(
                    Stage: req.Stage,
                    RoundScore: baseScore,
                    Criteria: new List<CriterionScoreDto>
                    {
                        new("Logic", baseScore, "Logic note", "LOGIC"),
                        new("Evidence", baseScore, "Evidence note", "EVIDENCE"),
                        new("Relevance", baseScore, "Relevance note", "RELEVANCE"),
                        new("Structure", baseScore, "Structure note", "STRUCTURE"),
                        new("Persuasiveness", baseScore, "Persuasiveness note", "PERSUASIVENESS")
                    },
                    ConsistencyNote: "Good",
                    Strengths: new List<string> { "Strong points" },
                    Weaknesses: new List<string>(),
                    Suggestions: new List<string>()
                );
                return Task.FromResult<EvaluateRoundResponse?>(res);
            }

            public Task<EvaluateSessionResponse?> EvaluateSessionAsync(EvaluateSessionRequest req, CancellationToken ct = default)
            {
                if (ExceptionToThrow != null) throw ExceptionToThrow;
                if (SessionEvaluator != null) return Task.FromResult(SessionEvaluator(req));

                decimal overall = req.Side == "pro" ? 8.0m : 6.0m;
                var res = new EvaluateSessionResponse(
                    OverallScore: overall,
                    StageBreakdown: new Dictionary<string, decimal> { { "opening", overall }, { "rebuttal", overall }, { "closing", overall } },
                    ProgressTrend: "Consistent",
                    OverallStrengths: new List<string> { "Strong debate" },
                    OverallWeaknesses: new List<string>(),
                    OverallSuggestions: new List<string>()
                );
                return Task.FromResult<EvaluateSessionResponse?>(res);
            }

            public Task<CoachingResultDto?> CoachArgumentAsync(ArgumentCoachingRequest req, CancellationToken ct = default)
                => Task.FromResult<CoachingResultDto?>(null);

            public Task<CoachingResultDto?> CoachRoundAsync(RoundCoachingRequest req, CancellationToken ct = default)
                => Task.FromResult<CoachingResultDto?>(null);
        }

        private async Task<(int orgId, int p1Id, int p2Id, int compId, int matchId, int sessionId)> SetupCompletedDebateMatchAsync(SystemDbContext context)
        {
            var org = new User { FullName = "Organizer", Email = $"org_{Guid.NewGuid():N}@test.com", PasswordHash = "h" };
            var p1 = new User { FullName = "Player PRO", Email = $"p1_{Guid.NewGuid():N}@test.com", PasswordHash = "h" };
            var p2 = new User { FullName = "Player CON", Email = $"p2_{Guid.NewGuid():N}@test.com", PasswordHash = "h" };
            context.Users.AddRange(org, p1, p2);

            var format = new DebateFormat { FormatName = "1 vs 1", MaxParticipants = 2, TotalRounds = 3, RoundDurationSeconds = 180, IsActive = true };
            context.DebateFormats.Add(format);
            await context.SaveChangesAsync();

            var competition = new Competition
            {
                Title = "Championship",
                CompetitionType = "SOLO",
                CreatedBy = org.UserId,
                FormatId = format.FormatId,
                Status = "Ongoing",
                StartDate = DateTime.UtcNow
            };
            context.Competitions.Add(competition);

            var round1 = new CompetitionRound { Competition = competition, RoundNumber = 1, RoundName = "Round 1", Status = "Ongoing" };
            var round2 = new CompetitionRound { Competition = competition, RoundNumber = 2, RoundName = "Round 2", Status = "Pending" };
            context.CompetitionRounds.AddRange(round1, round2);

            var nextMatch = new CompetitionMatch
            {
                Competition = competition,
                Round = round2,
                MatchNumber = 1,
                BracketPosition = 1,
                Status = "Scheduled"
            };
            context.CompetitionMatches.Add(nextMatch);

            var match = new CompetitionMatch
            {
                Competition = competition,
                Round = round1,
                MatchNumber = 1,
                BracketPosition = 1,
                NextMatch = nextMatch,
                Status = "Evaluating",
                EvaluationStatus = "Pending"
            };
            context.CompetitionMatches.Add(match);

            var mpPro = new MatchParticipant { Match = match, UserId = p1.UserId, Side = "PRO" };
            var mpCon = new MatchParticipant { Match = match, UserId = p2.UserId, Side = "CON" };
            context.MatchParticipants.AddRange(mpPro, mpCon);

            var topic = new Topic { Title = "AI Debate", Description = "Is AI helpful?", Difficulty = "Easy" };
            context.Topics.Add(topic);

            var session = new DebateSession
            {
                Topic = topic,
                FormatId = format.FormatId,
                CreatedBy = org.UserId,
                Status = SessionStatus.Completed,
                StartTime = DateTime.UtcNow.AddMinutes(-30),
                EndTime = DateTime.UtcNow
            };
            context.DebateSessions.Add(session);
            await context.SaveChangesAsync();

            match.DebateSessionId = session.DebateSessionId;

            var dpPro = new DebateParticipant { DebateSessionId = session.DebateSessionId, UserId = p1.UserId, Side = DebateSide.PRO };
            var dpCon = new DebateParticipant { DebateSessionId = session.DebateSessionId, UserId = p2.UserId, Side = DebateSide.CON };
            context.DebateParticipants.AddRange(dpPro, dpCon);

            for (int r = 1; r <= 3; r++)
            {
                var dr = new DebateRound
                {
                    DebateSessionId = session.DebateSessionId,
                    RoundNumber = r,
                    RoundType = r == 1 ? RoundType.OPENING : (r == 2 ? RoundType.REBUTTAL : RoundType.CLOSING),
                    StartTime = DateTime.UtcNow.AddMinutes(-20 + r * 5),
                    EndTime = DateTime.UtcNow.AddMinutes(-15 + r * 5)
                };
                context.DebateRounds.Add(dr);
                await context.SaveChangesAsync();

                context.Arguments.AddRange(
                    new Argument { RoundId = dr.RoundId, ParticipantId = dpPro.ParticipantId, Content = $"PRO round {r} argument" },
                    new Argument { RoundId = dr.RoundId, ParticipantId = dpCon.ParticipantId, Content = $"CON round {r} argument" }
                );
            }
            await context.SaveChangesAsync();

            return (org.UserId, p1.UserId, p2.UserId, competition.CompetitionId, match.CompetitionMatchId, session.DebateSessionId);
        }

        [Fact]
        public async Task Test01_Evaluation_DualPersistence_Success_WithMaterializedRubrics()
        {
            using var context = CreateContext();
            var (_, p1Id, _, _, matchId, sessionId) = await SetupCompletedDebateMatchAsync(context);

            var fakeClient = new MockAiClient();
            var debateRepo = new DebateRepository(context);
            var userRepo = new UserRepository(context);
            var debateService = new DebateService(debateRepo, userRepo, fakeClient);

            var evalResult = await debateService.EvaluateSessionAsync(p1Id, sessionId);
            Assert.True(evalResult.Success, evalResult.Message);

            // Verify AIJudgement persisted
            var judgement = await context.AIJudgements.FirstOrDefaultAsync(j => j.DebateSessionId == sessionId);
            Assert.NotNull(judgement);
            Assert.Equal("PRO", judgement!.SuggestedWinnerSide);

            // Verify JudgeScores materialized with ScoreSource = 'AI'
            var aiScores = await context.JudgeScores.Where(s => s.CompetitionMatchId == matchId && s.ScoreSource == "AI").ToListAsync();
            // 3 rounds x 2 sides x 5 criteria = 30 scores
            Assert.Equal(30, aiScores.Count);
            Assert.All(aiScores, s =>
            {
                Assert.Null(s.JudgeUserId);
                Assert.NotNull(s.DebateRoundId);
                Assert.True(s.Score >= 1 && s.Score <= 10);
            });

            // Verify CompetitionMatch updated to Completed
            var match = await context.CompetitionMatches.FindAsync(matchId);
            Assert.Equal("Completed", match!.EvaluationStatus);
            Assert.Null(match.EvaluationError);
        }

        [Fact]
        public async Task Test02_Evaluation_HttpFailure_MarksEvaluationFailed()
        {
            using var context = CreateContext();
            var (_, p1Id, _, _, matchId, sessionId) = await SetupCompletedDebateMatchAsync(context);

            var fakeClient = new MockAiClient
            {
                ExceptionToThrow = new HttpRequestException("500 Internal Server Error")
            };
            var debateRepo = new DebateRepository(context);
            var userRepo = new UserRepository(context);
            var debateService = new DebateService(debateRepo, userRepo, fakeClient);

            var result = await debateService.EvaluateSessionAsync(p1Id, sessionId);
            Assert.False(result.Success);

            var match = await context.CompetitionMatches.FindAsync(matchId);
            Assert.Equal("Failed", match!.EvaluationStatus);
            Assert.Contains("500 Internal Server Error", match.EvaluationError);
        }

        [Fact]
        public async Task Test03_Evaluation_Timeout_MarksEvaluationTimedOut()
        {
            using var context = CreateContext();
            var (_, p1Id, _, _, matchId, sessionId) = await SetupCompletedDebateMatchAsync(context);

            var fakeClient = new MockAiClient
            {
                ExceptionToThrow = new TimeoutException("AI HTTP request timed out")
            };
            var debateRepo = new DebateRepository(context);
            var userRepo = new UserRepository(context);
            var debateService = new DebateService(debateRepo, userRepo, fakeClient);

            var result = await debateService.EvaluateSessionAsync(p1Id, sessionId);
            Assert.False(result.Success);

            var match = await context.CompetitionMatches.FindAsync(matchId);
            Assert.Equal("TimedOut", match!.EvaluationStatus);
        }

        [Fact]
        public async Task Test04_Evaluation_MissingCriteria_RollsBackAndFails()
        {
            using var context = CreateContext();
            var (_, p1Id, _, _, matchId, sessionId) = await SetupCompletedDebateMatchAsync(context);

            var fakeClient = new MockAiClient
            {
                RoundEvaluator = req => new EvaluateRoundResponse(
                    Stage: req.Stage,
                    RoundScore: 7.0m,
                    Criteria: new List<CriterionScoreDto>
                    {
                        // Only 3 criteria returned instead of 5
                        new("Logic", 7, "note", "LOGIC"),
                        new("Evidence", 7, "note", "EVIDENCE"),
                        new("Relevance", 7, "note", "RELEVANCE")
                    },
                    ConsistencyNote: "ok",
                    Strengths: new List<string>(),
                    Weaknesses: new List<string>(),
                    Suggestions: new List<string>()
                )
            };
            var debateRepo = new DebateRepository(context);
            var userRepo = new UserRepository(context);
            var debateService = new DebateService(debateRepo, userRepo, fakeClient);

            var result = await debateService.EvaluateSessionAsync(p1Id, sessionId);
            Assert.False(result.Success);

            var match = await context.CompetitionMatches.FindAsync(matchId);
            Assert.Equal("Failed", match!.EvaluationStatus);
            Assert.Contains("incomplete criteria set", match.EvaluationError);

            // Clean rollback verification: no AI judgement or judge scores leaked
            Assert.Equal(0, await context.JudgeScores.CountAsync(s => s.CompetitionMatchId == matchId));
            Assert.Equal(0, await context.AIJudgements.CountAsync(j => j.DebateSessionId == sessionId));
        }

        [Fact]
        public async Task Test05_Evaluation_UnknownCriteria_RollsBackAndFails()
        {
            using var context = CreateContext();
            var (_, p1Id, _, _, matchId, sessionId) = await SetupCompletedDebateMatchAsync(context);

            var fakeClient = new MockAiClient
            {
                RoundEvaluator = req => new EvaluateRoundResponse(
                    Stage: req.Stage,
                    RoundScore: 7.0m,
                    Criteria: new List<CriterionScoreDto>
                    {
                        new("Logic", 7, "note", "LOGIC"),
                        new("Evidence", 7, "note", "EVIDENCE"),
                        new("Relevance", 7, "note", "RELEVANCE"),
                        new("Structure", 7, "note", "STRUCTURE"),
                        new("Humor", 7, "note", "HUMOR") // Unknown criterion!
                    },
                    ConsistencyNote: "ok",
                    Strengths: new List<string>(),
                    Weaknesses: new List<string>(),
                    Suggestions: new List<string>()
                )
            };
            var debateRepo = new DebateRepository(context);
            var userRepo = new UserRepository(context);
            var debateService = new DebateService(debateRepo, userRepo, fakeClient);

            var result = await debateService.EvaluateSessionAsync(p1Id, sessionId);
            Assert.False(result.Success);

            var match = await context.CompetitionMatches.FindAsync(matchId);
            Assert.Equal("Failed", match!.EvaluationStatus);
            Assert.Contains("unknown criterion", match.EvaluationError);
        }

        [Fact]
        public async Task Test06_Evaluation_InvalidScoreOutOfRange_RollsBackAndFails()
        {
            using var context = CreateContext();
            var (_, p1Id, _, _, matchId, sessionId) = await SetupCompletedDebateMatchAsync(context);

            var fakeClient = new MockAiClient
            {
                RoundEvaluator = req => new EvaluateRoundResponse(
                    Stage: req.Stage,
                    RoundScore: 15.0m,
                    Criteria: new List<CriterionScoreDto>
                    {
                        new("Logic", 15, "note", "LOGIC"), // > 10!
                        new("Evidence", 7, "note", "EVIDENCE"),
                        new("Relevance", 7, "note", "RELEVANCE"),
                        new("Structure", 7, "note", "STRUCTURE"),
                        new("Persuasiveness", 7, "note", "PERSUASIVENESS")
                    },
                    ConsistencyNote: "ok",
                    Strengths: new List<string>(),
                    Weaknesses: new List<string>(),
                    Suggestions: new List<string>()
                )
            };
            var debateRepo = new DebateRepository(context);
            var userRepo = new UserRepository(context);
            var debateService = new DebateService(debateRepo, userRepo, fakeClient);

            var result = await debateService.EvaluateSessionAsync(p1Id, sessionId);
            Assert.False(result.Success);

            var match = await context.CompetitionMatches.FindAsync(matchId);
            Assert.Equal("Failed", match!.EvaluationStatus);
            Assert.Contains("Score must be between 1 and 10", match.EvaluationError);
        }

        [Fact]
        public async Task Test07_Evaluation_RetryIdempotency_CleansUpPriorScores()
        {
            using var context = CreateContext();
            var (_, p1Id, _, _, matchId, sessionId) = await SetupCompletedDebateMatchAsync(context);

            var fakeClient = new MockAiClient();
            var debateRepo = new DebateRepository(context);
            var userRepo = new UserRepository(context);
            var debateService = new DebateService(debateRepo, userRepo, fakeClient);

            // Run evaluation 1
            var res1 = await debateService.EvaluateSessionAsync(p1Id, sessionId);
            Assert.True(res1.Success);

            // Run evaluation 2 (retry)
            var res2 = await debateService.EvaluateSessionAsync(p1Id, sessionId);
            Assert.True(res2.Success);

            // Assert exactly 1 AIJudgement and exactly 30 AI JudgeScores (no duplicates)
            Assert.Equal(1, await context.AIJudgements.CountAsync(j => j.DebateSessionId == sessionId));
            Assert.Equal(30, await context.JudgeScores.CountAsync(s => s.CompetitionMatchId == matchId && s.ScoreSource == "AI"));
        }

        [Fact]
        public async Task Test08_GetReview_ByBtcCreator_ReturnsFullMatrix()
        {
            using var context = CreateContext();
            var (orgId, p1Id, _, compId, matchId, sessionId) = await SetupCompletedDebateMatchAsync(context);

            var debateService = new DebateService(new DebateRepository(context), new UserRepository(context), new MockAiClient());
            await debateService.EvaluateSessionAsync(p1Id, sessionId);

            var tournamentService = new CompetitionTournamentService(context);
            var review = await tournamentService.GetReviewAsync(compId, matchId, orgId);

            Assert.True(review.Success);
            Assert.NotNull(review.Data);
            Assert.Equal("Completed", review.Data!.EvaluationStatus);
            Assert.Equal("PRO", review.Data.AiSuggestedWinnerSide);
            Assert.Equal(2, review.Data.Participants.Count);
            Assert.Equal(5, review.Data.Criteria.Count);
            Assert.Equal(30, review.Data.RoundRubrics!.Count);
        }

        [Fact]
        public async Task Test09_GetReview_ByNonBtc_ReturnsForbidden()
        {
            using var context = CreateContext();
            var (_, _, _, compId, matchId, _) = await SetupCompletedDebateMatchAsync(context);

            var outsider = new User { FullName = "Outsider", Email = "outsider@test.com", PasswordHash = "h" };
            context.Users.Add(outsider);
            await context.SaveChangesAsync();

            var tournamentService = new CompetitionTournamentService(context);
            var review = await tournamentService.GetReviewAsync(compId, matchId, outsider.UserId);

            Assert.False(review.Success);
            Assert.Equal(CompetitionErrorCodes.Forbidden, review.Errors as string);
        }

        [Fact]
        public async Task Test10_Finalize_ACCEPT_ComputesFinalScore_AdvancesBracket_NoJudgeScoresAdded()
        {
            using var context = CreateContext();
            var (orgId, p1Id, p2Id, compId, matchId, sessionId) = await SetupCompletedDebateMatchAsync(context);

            var debateService = new DebateService(new DebateRepository(context), new UserRepository(context), new MockAiClient());
            await debateService.EvaluateSessionAsync(p1Id, sessionId);

            var tournamentService = new CompetitionTournamentService(context);
            var finalizeReq = new FinalizeMatchRequest(decisionType: "ACCEPT");

            var result = await tournamentService.FinalizeMatchAsync(compId, matchId, orgId, finalizeReq);
            Assert.True(result.Success, result.Message);

            // Match completed
            var match = await context.CompetitionMatches.FindAsync(matchId);
            Assert.Equal("Completed", match!.Status);
            Assert.Equal("ACCEPT", match.DecisionType);
            Assert.Equal(p1Id, match.WinnerUserId);

            // Verify 0 JUDGE scores created
            Assert.Equal(0, await context.JudgeScores.CountAsync(s => s.CompetitionMatchId == matchId && s.ScoreSource == "JUDGE"));
            // 30 AI scores preserved
            Assert.Equal(30, await context.JudgeScores.CountAsync(s => s.CompetitionMatchId == matchId && s.ScoreSource == "AI"));

            // Verify participants have FinalScores
            var participants = await context.MatchParticipants.Where(p => p.CompetitionMatchId == matchId).ToListAsync();
            var pro = participants.Single(p => p.Side == "PRO");
            var con = participants.Single(p => p.Side == "CON");
            Assert.True(pro.IsWinner);
            Assert.False(con.IsWinner);
            Assert.True(pro.FinalScore > con.FinalScore);

            // Verify NextMatch has winner added
            var nextMatch = await context.CompetitionMatches.Include(m => m.Participants).SingleAsync(m => m.CompetitionMatchId == match.NextMatchId);
            Assert.Single(nextMatch.Participants, p => p.UserId == p1Id && p.Side == "PRO");
        }

        [Fact]
        public async Task Test11_Finalize_OVERRIDE_WithScoresAndReason_PreservesAiScores_ComputesWinnerFromJudgeScores()
        {
            using var context = CreateContext();
            var (orgId, p1Id, p2Id, compId, matchId, sessionId) = await SetupCompletedDebateMatchAsync(context);

            // AI evaluates and proposes PRO
            var debateService = new DebateService(new DebateRepository(context), new UserRepository(context), new MockAiClient());
            await debateService.EvaluateSessionAsync(p1Id, sessionId);

            var tournamentService = new CompetitionTournamentService(context);
            var participants = await context.MatchParticipants.Where(p => p.CompetitionMatchId == matchId).ToListAsync();
            var proId = participants.Single(p => p.Side == "PRO").MatchParticipantId;
            var conId = participants.Single(p => p.Side == "CON").MatchParticipantId;

            var criteria = await context.DebateCriteria.Where(c => c.IsActive).ToListAsync();
            var rounds = await context.DebateRounds.Where(r => r.DebateSessionId == sessionId).ToListAsync();

            // BTC overrides: scores CON higher (10 for CON, 5 for PRO in every round)
            var judgeScoresInput = new List<RoundScoreInput>();
            foreach (var r in rounds)
            {
                foreach (var c in criteria)
                {
                    judgeScoresInput.Add(new RoundScoreInput(r.RoundId, proId, c.CriteriaId, 5.0m, "PRO round note"));
                    judgeScoresInput.Add(new RoundScoreInput(r.RoundId, conId, c.CriteriaId, 10.0m, "CON stronger rebuttal"));
                }
            }

            var overrideReq = new FinalizeMatchRequest(
                decisionType: "OVERRIDE",
                decisionReason: "BTC determined CON rebuttal was substantially more persuasive and evidence-backed.",
                scores: judgeScoresInput
            );

            var result = await tournamentService.FinalizeMatchAsync(compId, matchId, orgId, overrideReq);
            Assert.True(result.Success, result.Message);

            // CON is declared official winner despite AI proposing PRO!
            var match = await context.CompetitionMatches.FindAsync(matchId);
            Assert.Equal("Completed", match!.Status);
            Assert.Equal("OVERRIDE", match.DecisionType);
            Assert.Equal(p2Id, match.WinnerUserId);

            // Both 30 AI scores AND 30 JUDGE scores exist
            Assert.Equal(30, await context.JudgeScores.CountAsync(s => s.CompetitionMatchId == matchId && s.ScoreSource == "AI"));
            Assert.Equal(30, await context.JudgeScores.CountAsync(s => s.CompetitionMatchId == matchId && s.ScoreSource == "JUDGE"));

            // NextMatch has CON winner
            var nextMatch = await context.CompetitionMatches.Include(m => m.Participants).SingleAsync(m => m.CompetitionMatchId == match.NextMatchId);
            Assert.Single(nextMatch.Participants, p => p.UserId == p2Id);
        }

        [Fact]
        public async Task Test12_Finalize_OVERRIDE_WhenTie_RejectsWithBadRequest_DoesNotAdvanceBracket()
        {
            using var context = CreateContext();
            var (orgId, p1Id, _, compId, matchId, sessionId) = await SetupCompletedDebateMatchAsync(context);

            var debateService = new DebateService(new DebateRepository(context), new UserRepository(context), new MockAiClient());
            await debateService.EvaluateSessionAsync(p1Id, sessionId);

            var tournamentService = new CompetitionTournamentService(context);
            var participants = await context.MatchParticipants.Where(p => p.CompetitionMatchId == matchId).ToListAsync();
            var proId = participants.Single(p => p.Side == "PRO").MatchParticipantId;
            var conId = participants.Single(p => p.Side == "CON").MatchParticipantId;
            var criteria = await context.DebateCriteria.Where(c => c.IsActive).ToListAsync();
            var rounds = await context.DebateRounds.Where(r => r.DebateSessionId == sessionId).ToListAsync();

            // Tie scores: exactly 7.0 for both sides
            var tieScores = new List<RoundScoreInput>();
            foreach (var r in rounds)
            {
                foreach (var c in criteria)
                {
                    tieScores.Add(new RoundScoreInput(r.RoundId, proId, c.CriteriaId, 7.0m));
                    tieScores.Add(new RoundScoreInput(r.RoundId, conId, c.CriteriaId, 7.0m));
                }
            }

            var overrideReq = new FinalizeMatchRequest(
                decisionType: "OVERRIDE",
                decisionReason: "Attempting to submit equal scores",
                scores: tieScores
            );

            var result = await tournamentService.FinalizeMatchAsync(compId, matchId, orgId, overrideReq);
            Assert.False(result.Success);
            Assert.Contains("tie", result.Message, StringComparison.OrdinalIgnoreCase);

            // Match remains Evaluating, next match does NOT advance
            var match = await context.CompetitionMatches.FindAsync(matchId);
            Assert.Equal("Evaluating", match!.Status);
            var nextMatch = await context.CompetitionMatches.Include(m => m.Participants).SingleAsync(m => m.CompetitionMatchId == match.NextMatchId);
            Assert.Empty(nextMatch.Participants);
        }

        [Fact]
        public async Task Test13_Finalize_OVERRIDE_MissingReason_RejectsWithBadRequest()
        {
            using var context = CreateContext();
            var (orgId, p1Id, _, compId, matchId, sessionId) = await SetupCompletedDebateMatchAsync(context);

            var debateService = new DebateService(new DebateRepository(context), new UserRepository(context), new MockAiClient());
            await debateService.EvaluateSessionAsync(p1Id, sessionId);

            var tournamentService = new CompetitionTournamentService(context);
            var participants = await context.MatchParticipants.Where(p => p.CompetitionMatchId == matchId).ToListAsync();
            var proId = participants.Single(p => p.Side == "PRO").MatchParticipantId;
            var conId = participants.Single(p => p.Side == "CON").MatchParticipantId;
            var criteria = await context.DebateCriteria.Where(c => c.IsActive).ToListAsync();
            var rounds = await context.DebateRounds.Where(r => r.DebateSessionId == sessionId).ToListAsync();

            var scores = new List<RoundScoreInput>();
            foreach (var r in rounds)
            {
                foreach (var c in criteria)
                {
                    scores.Add(new RoundScoreInput(r.RoundId, proId, c.CriteriaId, 8.0m));
                    scores.Add(new RoundScoreInput(r.RoundId, conId, c.CriteriaId, 6.0m));
                }
            }

            var overrideReq = new FinalizeMatchRequest(
                decisionType: "OVERRIDE",
                decisionReason: "", // Empty reason!
                scores: scores
            );

            var result = await tournamentService.FinalizeMatchAsync(compId, matchId, orgId, overrideReq);
            Assert.False(result.Success);
            Assert.Contains("DecisionReason is required", result.Message);
        }

        [Fact]
        public async Task Test14_Finalize_MANUAL_FINALIZE_WhenFailed_Succeeds()
        {
            using var context = CreateContext();
            var (orgId, p1Id, _, compId, matchId, sessionId) = await SetupCompletedDebateMatchAsync(context);

            // Match failed evaluation
            var match = await context.CompetitionMatches.FindAsync(matchId);
            match!.EvaluationStatus = "Failed";
            match.EvaluationError = "AI service timeout 504";
            await context.SaveChangesAsync();

            var tournamentService = new CompetitionTournamentService(context);
            var participants = await context.MatchParticipants.Where(p => p.CompetitionMatchId == matchId).ToListAsync();
            var proId = participants.Single(p => p.Side == "PRO").MatchParticipantId;
            var conId = participants.Single(p => p.Side == "CON").MatchParticipantId;
            var criteria = await context.DebateCriteria.Where(c => c.IsActive).ToListAsync();
            var rounds = await context.DebateRounds.Where(r => r.DebateSessionId == sessionId).ToListAsync();

            var scores = new List<RoundScoreInput>();
            foreach (var r in rounds)
            {
                foreach (var c in criteria)
                {
                    scores.Add(new RoundScoreInput(r.RoundId, proId, c.CriteriaId, 9.0m));
                    scores.Add(new RoundScoreInput(r.RoundId, conId, c.CriteriaId, 6.0m));
                }
            }

            var manualReq = new FinalizeMatchRequest(
                decisionType: "MANUAL_FINALIZE",
                decisionReason: "AI service was unreachable; human panel evaluated live recordings.",
                scores: scores
            );

            var result = await tournamentService.FinalizeMatchAsync(compId, matchId, orgId, manualReq);
            Assert.True(result.Success, result.Message);

            var updatedMatch = await context.CompetitionMatches.FindAsync(matchId);
            Assert.Equal("Completed", updatedMatch!.Status);
            Assert.Equal("MANUAL_FINALIZE", updatedMatch.DecisionType);
            Assert.Equal(p1Id, updatedMatch.WinnerUserId);
        }

        [Fact]
        public async Task Test15_Finalize_MANUAL_FINALIZE_WhenCompletedOrRunning_RejectsWithConflict()
        {
            using var context = CreateContext();
            var (orgId, _, _, compId, matchId, _) = await SetupCompletedDebateMatchAsync(context);

            // AI evaluation status is Running, NOT Failed
            var match = await context.CompetitionMatches.FindAsync(matchId);
            match!.EvaluationStatus = "Running";
            await context.SaveChangesAsync();

            var tournamentService = new CompetitionTournamentService(context);
            var manualReq = new FinalizeMatchRequest(
                decisionType: "MANUAL_FINALIZE",
                decisionReason: "Premature manual finalize attempt",
                scores: new List<RoundScoreInput>()
            );

            var result = await tournamentService.FinalizeMatchAsync(compId, matchId, orgId, manualReq);
            Assert.False(result.Success);
            Assert.Equal(CompetitionErrorCodes.Conflict, result.Errors as string);
            Assert.Contains("MANUAL_FINALIZE is only allowed when AI evaluation has Failed or TimedOut", result.Message);
        }

        [Fact]
        public async Task Test16_Finalize_NonBtcCreator_ReturnsForbidden()
        {
            using var context = CreateContext();
            var (_, _, _, compId, matchId, _) = await SetupCompletedDebateMatchAsync(context);

            var outsider = new User { FullName = "Random User", Email = "random@test.com", PasswordHash = "h" };
            context.Users.Add(outsider);
            await context.SaveChangesAsync();

            var tournamentService = new CompetitionTournamentService(context);
            var req = new FinalizeMatchRequest(decisionType: "ACCEPT");

            var result = await tournamentService.FinalizeMatchAsync(compId, matchId, outsider.UserId, req);
            Assert.False(result.Success);
            Assert.Equal(CompetitionErrorCodes.Forbidden, result.Errors as string);
        }

        [Fact]
        public async Task Test17_Finalize_FinalMatch_CompletesCompetition()
        {
            using var context = CreateContext();
            var (orgId, p1Id, _, compId, _, sessionId) = await SetupCompletedDebateMatchAsync(context);

            // Remove nextMatch to make this match the final championship match
            var match = await context.CompetitionMatches.FirstAsync(m => m.NextMatchId != null);
            var next = await context.CompetitionMatches.FindAsync(match.NextMatchId);
            match.NextMatchId = null;
            context.CompetitionMatches.Remove(next!);
            var r2 = await context.CompetitionRounds.FirstAsync(r => r.RoundNumber == 2);
            context.CompetitionRounds.Remove(r2);
            await context.SaveChangesAsync();

            var debateService = new DebateService(new DebateRepository(context), new UserRepository(context), new MockAiClient());
            await debateService.EvaluateSessionAsync(p1Id, sessionId);

            var tournamentService = new CompetitionTournamentService(context);
            var result = await tournamentService.FinalizeMatchAsync(compId, match.CompetitionMatchId, orgId, new FinalizeMatchRequest(decisionType: "ACCEPT"));

            Assert.True(result.Success, result.Message);

            var comp = await context.Competitions.FindAsync(compId);
            Assert.Equal("Completed", comp!.Status);
        }
    }
}
