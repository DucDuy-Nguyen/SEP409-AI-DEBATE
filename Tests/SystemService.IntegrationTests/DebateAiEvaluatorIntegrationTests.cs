using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Data.Sqlite;
using Microsoft.EntityFrameworkCore;
using SystemService.BLL.Common.Responses;
using SystemService.BLL.DTOs.AI;
using SystemService.BLL.DTOs.Debate;
using SystemService.BLL.Services.AI.Interfaces;
using SystemService.BLL.Services.Debate.Implementations;
using SystemService.DAL.Context;
using SystemService.DAL.Entities.Debate;
using SystemService.DAL.Entities.Debate.Enums;
using SystemService.DAL.Entities.Identity;
using SystemService.DAL.Repositories.Debate.Implementations;
using SystemService.DAL.Repositories.Identity.Implementations;
using Xunit;

namespace SystemService.IntegrationTests
{
    public class DebateAiEvaluatorIntegrationTests : IDisposable
    {
        private readonly SqliteConnection _connection;
        private readonly DbContextOptions<SystemDbContext> _options;

        public DebateAiEvaluatorIntegrationTests()
        {
            _connection = new SqliteConnection("DataSource=:memory:");
            _connection.Open();

            _options = new DbContextOptionsBuilder<SystemDbContext>()
                .UseSqlite(_connection)
                .Options;

            using var context = new SystemDbContext(_options);
            context.Database.EnsureCreated();
        }

        public void Dispose()
        {
            _connection.Dispose();
        }

        private class FakeAiEvaluatorClient : IAiEvaluatorClient
        {
            public int EvaluateArgumentCallCount { get; private set; }
            public int EvaluateRoundCallCount { get; private set; }
            public int EvaluateSessionCallCount { get; private set; }

            public Task<EvaluateArgumentResponse?> EvaluateArgumentAsync(EvaluateArgumentRequest req, CancellationToken ct = default)
            {
                EvaluateArgumentCallCount++;
                var response = new EvaluateArgumentResponse(
                    OverallScore: 8.0m,
                    OverallReasoning: "Strong logical structure and clear relevance.",
                    Criteria: new List<CriterionScoreDto>
                    {
                        new("logic", 4, "Sound reasoning"),
                        new("evidence", 4, "Supported with relevant points"),
                        new("relevance", 4, "Directly addresses the motion"),
                        new("structure", 4, "Clear organization"),
                        new("persuasiveness", 4, "Compelling argument")
                    },
                    Strengths: new List<string> { "Clear core claim", "Good organization" },
                    Weaknesses: new List<string> { "Could provide more statistical data" },
                    Suggestions: new List<string> { "Add concrete examples in rebuttal" },
                    RawModelOutput: "{\"overall_score\": 8.0}"
                );
                return Task.FromResult<EvaluateArgumentResponse?>(response);
            }

            public Task<EvaluateRoundResponse?> EvaluateRoundAsync(EvaluateRoundRequest req, CancellationToken ct = default)
            {
                EvaluateRoundCallCount++;
                decimal score = req.Side == "pro" ? 8.5m : 7.0m;
                var response = new EvaluateRoundResponse(
                    Stage: req.Stage,
                    RoundScore: score,
                    Criteria: new List<CriterionScoreDto>
                    {
                        new("logic", req.Side == "pro" ? 4 : 3, "Logic score"),
                        new("evidence", 4, "Evidence score"),
                        new("relevance", 4, "Relevance score"),
                        new("structure", req.Side == "pro" ? 5 : 4, "Structure score"),
                        new("persuasiveness", 4, "Persuasiveness score")
                    },
                    ConsistencyNote: "Maintained consistent stance throughout the round.",
                    Strengths: new List<string> { "Strong rebuttal", "Good pacing" },
                    Weaknesses: new List<string> { "Minor gaps in evidence" },
                    Suggestions: new List<string> { "Address opponent claims directly" }
                );
                return Task.FromResult<EvaluateRoundResponse?>(response);
            }

            public Task<EvaluateSessionResponse?> EvaluateSessionAsync(EvaluateSessionRequest req, CancellationToken ct = default)
            {
                EvaluateSessionCallCount++;
                decimal overallScore = req.Side == "pro" ? 8.5m : 7.2m;
                var response = new EvaluateSessionResponse(
                    OverallScore: overallScore,
                    StageBreakdown: new Dictionary<string, decimal>
                    {
                        { "opening", req.Side == "pro" ? 8.0m : 7.0m },
                        { "rebuttal", req.Side == "pro" ? 9.0m : 7.5m },
                        { "closing", req.Side == "pro" ? 8.5m : 7.1m }
                    },
                    ProgressTrend: req.Side == "pro" ? "Tiến bộ rõ rệt qua từng vòng tranh biện." : "Ổn định nhưng cần tăng cường dẫn chứng.",
                    OverallStrengths: new List<string> { "Lập luận sắc bén", "Cấu trúc rõ ràng" },
                    OverallWeaknesses: new List<string> { "Cần thêm số liệu thực tế" },
                    OverallSuggestions: new List<string> { "Luyện tập thêm phần kết luận" },
                    RawModelOutput: "{\"overall_score\": " + overallScore + "}"
                );
                return Task.FromResult<EvaluateSessionResponse?>(response);
            }

            public Task<CoachingResultDto?> CoachArgumentAsync(ArgumentCoachingRequest req, CancellationToken ct = default)
            {
                var result = new CoachingResultDto(
                    FocusCriteria: new List<CriterionCoachingDto>
                    {
                        new("evidence", 3, "Chưa đủ số liệu", new List<string> { "Dẫn chứng từ báo cáo", "Ví dụ thực tế" }, "Nêu nguồn cụ thể")
                    },
                    IdeaDevelopment: new IdeaDevelopmentDto("Luận điểm chính", new List<string> { "Mở rộng góc nhìn kinh tế" }),
                    RawModelOutput: null
                );
                return Task.FromResult<CoachingResultDto?>(result);
            }

            public Task<CoachingResultDto?> CoachRoundAsync(RoundCoachingRequest req, CancellationToken ct = default)
            {
                var result = new CoachingResultDto(
                    FocusCriteria: new List<CriterionCoachingDto>
                    {
                        new("logic", 4, "Lập luận tốt", new List<string> { "Giữ vững luận điểm" }, "Áp dụng cho vòng sau")
                    },
                    IdeaDevelopment: new IdeaDevelopmentDto("Cốt lõi vòng này", new List<string> { "Phản bác triệt để hơn" }),
                    RawModelOutput: null
                );
                return Task.FromResult<CoachingResultDto?>(result);
            }
        }

        private async Task<(int userProId, int userConId, int sessionId, int argumentId)> SetupCompletedDebateSessionAsync(SystemDbContext context)
        {
            var userPro = new User { FullName = "Nguyễn Văn Pro", Email = "pro@debate.com", PasswordHash = "hash" };
            var userCon = new User { FullName = "Trần Thị Con", Email = "con@debate.com", PasswordHash = "hash" };
            context.Users.AddRange(userPro, userCon);

            var topic = new Topic
            {
                Title = "THBT AI will replace software engineers",
                Description = "AI is rapidly advancing in software development",
                Difficulty = "Medium",
                IsActive = true
            };
            context.Topics.Add(topic);

            var format = new DebateFormat
            {
                FormatName = "1 vs 1",
                MaxParticipants = 2,
                TotalRounds = 3,
                RoundDurationSeconds = 180,
                IsActive = true
            };
            context.DebateFormats.Add(format);
            await context.SaveChangesAsync();

            var session = new DebateSession
            {
                TopicId = topic.TopicId,
                FormatId = format.FormatId,
                CreatedBy = userPro.UserId,
                Status = SessionStatus.Completed,
                StartTime = DateTime.UtcNow.AddMinutes(-30),
                EndTime = DateTime.UtcNow,
                CreatedAt = DateTime.UtcNow.AddMinutes(-35)
            };

            var partPro = new DebateParticipant
            {
                UserId = userPro.UserId,
                ParticipantType = ParticipantType.USER,
                Side = DebateSide.PRO,
                JoinedAt = DateTime.UtcNow.AddMinutes(-35)
            };
            var partCon = new DebateParticipant
            {
                UserId = userCon.UserId,
                ParticipantType = ParticipantType.USER,
                Side = DebateSide.CON,
                JoinedAt = DateTime.UtcNow.AddMinutes(-35)
            };
            session.Participants.Add(partPro);
            session.Participants.Add(partCon);

            var round1 = new DebateRound
            {
                RoundNumber = 1,
                RoundType = RoundType.OPENING,
                StartTime = DateTime.UtcNow.AddMinutes(-30),
                EndTime = DateTime.UtcNow.AddMinutes(-20),
                CreatedAt = DateTime.UtcNow.AddMinutes(-35)
            };
            var round2 = new DebateRound
            {
                RoundNumber = 2,
                RoundType = RoundType.REBUTTAL,
                StartTime = DateTime.UtcNow.AddMinutes(-20),
                EndTime = DateTime.UtcNow.AddMinutes(-10),
                CreatedAt = DateTime.UtcNow.AddMinutes(-35)
            };
            var round3 = new DebateRound
            {
                RoundNumber = 3,
                RoundType = RoundType.CLOSING,
                StartTime = DateTime.UtcNow.AddMinutes(-10),
                EndTime = DateTime.UtcNow,
                CreatedAt = DateTime.UtcNow.AddMinutes(-35)
            };

            session.DebateRounds.Add(round1);
            session.DebateRounds.Add(round2);
            session.DebateRounds.Add(round3);

            var arg1 = new Argument
            {
                Round = round1,
                Participant = partPro,
                Content = "AI accelerates development by automating routine tasks.",
                WordCount = 8,
                SubmittedAt = DateTime.UtcNow.AddMinutes(-29)
            };
            var arg2 = new Argument
            {
                Round = round1,
                Participant = partCon,
                Content = "AI cannot replace human creativity, judgment, and domain understanding.",
                WordCount = 10,
                SubmittedAt = DateTime.UtcNow.AddMinutes(-25)
            };
            var arg3 = new Argument
            {
                Round = round2,
                Participant = partPro,
                Content = "Creative AI models are already writing complex architecture patterns.",
                WordCount = 9,
                SubmittedAt = DateTime.UtcNow.AddMinutes(-19)
            };
            var arg4 = new Argument
            {
                Round = round2,
                Participant = partCon,
                Content = "Models require supervision and prompt curation by experienced engineers.",
                WordCount = 9,
                SubmittedAt = DateTime.UtcNow.AddMinutes(-15)
            };
            var arg5 = new Argument
            {
                Round = round3,
                Participant = partPro,
                Content = "In conclusion, the future of coding is largely autonomous.",
                WordCount = 9,
                SubmittedAt = DateTime.UtcNow.AddMinutes(-9)
            };
            var arg6 = new Argument
            {
                Round = round3,
                Participant = partCon,
                Content = "Engineers will evolve into orchestrators, remaining indispensable.",
                WordCount = 7,
                SubmittedAt = DateTime.UtcNow.AddMinutes(-5)
            };

            round1.Arguments.Add(arg1);
            round1.Arguments.Add(arg2);
            round2.Arguments.Add(arg3);
            round2.Arguments.Add(arg4);
            round3.Arguments.Add(arg5);
            round3.Arguments.Add(arg6);

            context.DebateSessions.Add(session);
            await context.SaveChangesAsync();

            return (userPro.UserId, userCon.UserId, session.DebateSessionId, arg1.ArgumentId);
        }

        [Fact]
        public async Task EvaluateArgument_ReturnsAccurateScoresAndFeedback()
        {
            using var context = new SystemDbContext(_options);
            var (proId, _, sessionId, argumentId) = await SetupCompletedDebateSessionAsync(context);

            var fakeClient = new FakeAiEvaluatorClient();
            var service = new DebateService(
                new DebateRepository(context),
                new UserRepository(context),
                fakeClient
            );

            // Act
            var result = await service.EvaluateArgumentAsync(proId, sessionId, argumentId);

            // Assert
            Assert.True(result.Success);
            Assert.NotNull(result.Data);
            Assert.Equal(argumentId, result.Data.ArgumentId);
            Assert.Equal(8.0m, result.Data.OverallScore);
            Assert.Equal("opening", result.Data.Stage);
            Assert.Equal("PRO", result.Data.Side);
            Assert.Equal(5, result.Data.Criteria.Count);
            Assert.Contains(result.Data.Strengths, s => s.Contains("Clear core claim"));
            Assert.Equal(1, fakeClient.EvaluateArgumentCallCount);
        }

        [Fact]
        public async Task EvaluateSession_CalculatesScores_DeterminesWinner_AndStoresAIJudgement()
        {
            using var context = new SystemDbContext(_options);
            var (proId, conId, sessionId, _) = await SetupCompletedDebateSessionAsync(context);

            var fakeClient = new FakeAiEvaluatorClient();
            var service = new DebateService(
                new DebateRepository(context),
                new UserRepository(context),
                fakeClient
            );

            // Act
            var result = await service.EvaluateSessionAsync(proId, sessionId);

            // Assert
            Assert.True(result.Success);
            Assert.NotNull(result.Data);
            Assert.Equal(sessionId, result.Data.SessionId);
            Assert.Equal("PRO", result.Data.SuggestedWinnerSide);
            Assert.Equal(8.5m, result.Data.OverallScorePro);
            Assert.Equal(7.2m, result.Data.OverallScoreCon);
            Assert.True(result.Data.ConfidenceScore > 0.5m);
            Assert.NotNull(result.Data.ProEvaluation);
            Assert.NotNull(result.Data.ConEvaluation);
            Assert.Equal(3, result.Data.ProEvaluation!.RoundEvaluations.Count);
            Assert.Equal(3, result.Data.ConEvaluation!.RoundEvaluations.Count);

            // Verify stored AIJudgement in database
            var storedJudgement = await context.AIJudgements
                .FirstOrDefaultAsync(j => j.DebateSessionId == sessionId);
            Assert.NotNull(storedJudgement);
            Assert.Equal("PRO", storedJudgement.SuggestedWinnerSide);
            Assert.Equal(8.5m, storedJudgement.OverallScorePro);
            Assert.Equal(7.2m, storedJudgement.OverallScoreCon);
            Assert.Contains("PRO", storedJudgement.Summary);
        }

        [Fact]
        public async Task GetSessionEvaluation_ReturnsCachedJudgement_WithoutReEvaluating()
        {
            using var context = new SystemDbContext(_options);
            var (proId, _, sessionId, _) = await SetupCompletedDebateSessionAsync(context);

            var fakeClient = new FakeAiEvaluatorClient();
            var service = new DebateService(
                new DebateRepository(context),
                new UserRepository(context),
                fakeClient
            );

            // Initial evaluation
            var firstEval = await service.EvaluateSessionAsync(proId, sessionId);
            Assert.True(firstEval.Success);
            int initialRoundCalls = fakeClient.EvaluateRoundCallCount;
            int initialSessionCalls = fakeClient.EvaluateSessionCallCount;

            // Second call via GetSessionEvaluationAsync
            var getResult = await service.GetSessionEvaluationAsync(proId, sessionId);

            // Assert
            Assert.True(getResult.Success);
            Assert.NotNull(getResult.Data);
            Assert.Equal(firstEval.Data!.JudgementId, getResult.Data.JudgementId);
            Assert.Equal(firstEval.Data.SuggestedWinnerSide, getResult.Data.SuggestedWinnerSide);
            Assert.Equal(firstEval.Data.OverallScorePro, getResult.Data.OverallScorePro);

            // Verify no additional AI calls were made (cached in DB AIJudgements)
            Assert.Equal(initialRoundCalls, fakeClient.EvaluateRoundCallCount);
            Assert.Equal(initialSessionCalls, fakeClient.EvaluateSessionCallCount);
        }

        [Fact]
        public async Task SubmitArgument_OnFinalTurn_AutomaticallyTriggersEvaluation()
        {
            using var context = new SystemDbContext(_options);
            var userPro = new User { FullName = "Host Pro", Email = "host@debate.com", PasswordHash = "hash" };
            var userCon = new User { FullName = "Opponent Con", Email = "opp@debate.com", PasswordHash = "hash" };
            context.Users.AddRange(userPro, userCon);

            var topic = new Topic { Title = "Test Motion", Difficulty = "Easy", IsActive = true };
            var format = new DebateFormat { FormatName = "1 vs 1", MaxParticipants = 2, TotalRounds = 1, RoundDurationSeconds = 180 };
            context.Topics.Add(topic);
            context.DebateFormats.Add(format);
            await context.SaveChangesAsync();

            var session = new DebateSession
            {
                TopicId = topic.TopicId,
                FormatId = format.FormatId,
                CreatedBy = userPro.UserId,
                Status = SessionStatus.InProgress,
                StartTime = DateTime.UtcNow
            };
            var pPro = new DebateParticipant { UserId = userPro.UserId, ParticipantType = ParticipantType.USER, Side = DebateSide.PRO };
            var pCon = new DebateParticipant { UserId = userCon.UserId, ParticipantType = ParticipantType.USER, Side = DebateSide.CON };
            session.Participants.Add(pPro);
            session.Participants.Add(pCon);

            var round1 = new DebateRound { RoundNumber = 1, RoundType = RoundType.OPENING, StartTime = DateTime.UtcNow };
            round1.Arguments.Add(new Argument
            {
                Participant = pPro,
                Content = "Opening PRO speech.",
                SubmittedAt = DateTime.UtcNow.AddSeconds(-10)
            });
            session.DebateRounds.Add(round1);

            context.DebateSessions.Add(session);
            await context.SaveChangesAsync();

            var fakeClient = new FakeAiEvaluatorClient();
            var service = new DebateService(
                new DebateRepository(context),
                new UserRepository(context),
                fakeClient
            );

            // CON submits final argument for round 1 (which is the only round)
            var submitResult = await service.SubmitArgumentAsync(userCon.UserId, session.DebateSessionId, new SubmitArgumentRequest
            {
                Content = "Opening CON speech concluding the debate."
            });

            // Assert
            Assert.True(submitResult.Success);
            Assert.Equal(SessionStatus.Completed, submitResult.Data!.Status);

            // Verify auto-evaluation stored AIJudgement
            var storedJudgement = await context.AIJudgements
                .FirstOrDefaultAsync(j => j.DebateSessionId == session.DebateSessionId);
            Assert.NotNull(storedJudgement);
            Assert.True(fakeClient.EvaluateRoundCallCount > 0);
        }
    }
}
