using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Diagnostics;
using Microsoft.Extensions.DependencyInjection;
using SystemService.BLL.Common.Responses;
using SystemService.BLL.DTOs.Debate;
using SystemService.BLL.Services.AI.Interfaces;
using SystemService.BLL.Services.Debate.Implementations;
using SystemService.BLL.Services.Debate.Interfaces;
using SystemService.DAL.Context;
using SystemService.DAL.Entities.Debate;
using SystemService.DAL.Entities.Debate.Enums;
using SystemService.DAL.Entities.Identity;
using SystemService.DAL.Repositories.Debate.Implementations;
using SystemService.DAL.Repositories.Identity.Implementations;

namespace SystemService.Tests.Debate
{
    /// <summary>
    /// Real DebateService + repositories on an EF InMemory database. Every call uses a fresh DbContext
    /// (like one request = one scoped context in the API), all sharing the same in-memory store.
    /// </summary>
    internal sealed class DebateTestHarness : IDisposable
    {
        public const int UserA = 1;
        public const int UserB = 2;
        public const int Outsider = 3;

        private readonly string _databaseName = Guid.NewGuid().ToString();
        private readonly List<SystemDbContext> _contexts = new();

        public DebateTestHarness()
        {
            using var context = CreateContext();
            context.Users.AddRange(
                new User { UserId = UserA, FullName = "Learner A", Email = "a@test.local" },
                new User { UserId = UserB, FullName = "Learner B", Email = "b@test.local" },
                new User { UserId = Outsider, FullName = "Outsider", Email = "c@test.local" });
            context.DebateFormats.AddRange(
                new DebateFormat { FormatId = 1, FormatName = "User vs AI", MaxParticipants = 2 },
                new DebateFormat { FormatId = 2, FormatName = "1 vs 1", MaxParticipants = 2 });
            context.SaveChanges();
        }

        public SystemDbContext CreateContext()
        {
            var options = new DbContextOptionsBuilder<SystemDbContext>()
                .UseInMemoryDatabase(_databaseName)
                .ConfigureWarnings(w => w.Ignore(InMemoryEventId.TransactionIgnoredWarning))
                .Options;
            return new SystemDbContext(options);
        }

        private ServiceProvider? _provider;
        private DebateEvaluationCoordinator? _coordinator;
        private IAiEvaluatorClient? _lastEvaluator;

        /// <summary>
        /// One per harness, like the API's singleton, WITH a scope factory like the API: an evaluation runs on a service
        /// (and DbContext) of its own scope, never on the caller's context, which the caller keeps using.
        /// </summary>
        public DebateEvaluationCoordinator Coordinator
        {
            get
            {
                lock (_contexts)
                {
                    if (_coordinator == null)
                    {
                        var services = new ServiceCollection();
                        // The evaluator of the evaluation's scope = the one of the last service that had one (like DI)
                        services.AddScoped<IDebateService>(_ => Build(_lastEvaluator));
                        _provider = services.BuildServiceProvider();
                        _coordinator = new DebateEvaluationCoordinator(_provider.GetRequiredService<IServiceScopeFactory>());
                    }
                    return _coordinator;
                }
            }
        }

        /// <summary>Evaluator used by every service built here when none is passed (null = AI evaluation off).</summary>
        public IAiEvaluatorClient? AiEvaluator { get; set; }

        public DebateService NewService(IAiEvaluatorClient? aiEvaluatorClient = null)
        {
            var evaluator = aiEvaluatorClient ?? AiEvaluator;
            if (evaluator != null)
            {
                _lastEvaluator = evaluator;
            }
            return Build(evaluator);
        }

        private DebateService Build(IAiEvaluatorClient? evaluator)
        {
            var context = CreateContext();
            lock (_contexts)
            {
                _contexts.Add(context);
            }
            return new DebateService(new DebateRepository(context), new UserRepository(context),
                evaluator, logger: null, evaluationCoordinator: Coordinator);
        }

        public async Task<int> StartAiSessionAsync(DebateSide userSide)
        {
            var created = await NewService().CreateAiPracticeSessionAsync(UserA, new CreateAiPracticeSessionRequest
            {
                Title = "Motion",
                Topic = "Students should not have homework",
                UserSide = userSide,
                IsAI = true
            });
            Assert.True(created.Success, created.Message);

            var started = await NewService().StartDebateSessionAsync(UserA, created.Data!.SessionId);
            Assert.True(started.Success, started.Message);
            return created.Data.SessionId;
        }

        public async Task<int> StartP2pSessionAsync(DebateSide creatorSide)
        {
            var created = await NewService().CreateP2pSessionAsync(UserA, new CreateP2pSessionRequest
            {
                Title = "Motion",
                Topic = "Students should not have homework",
                UserSide = creatorSide,
                IsAI = false
            });
            Assert.True(created.Success, created.Message);
            int sessionId = created.Data!.SessionId;

            var joined = await NewService().JoinP2pSessionAsync(UserB, sessionId, new JoinSessionRequest());
            Assert.True(joined.Success, joined.Message);

            var started = await NewService().StartDebateSessionAsync(UserA, sessionId);
            Assert.True(started.Success, started.Message);
            return sessionId;
        }

        public Task<ApiResponse<DebateSessionResponse>> UserSubmitsAsync(int userId, int sessionId, string content = "User speech")
        {
            return NewService().SubmitArgumentAsync(userId, sessionId, new SubmitArgumentRequest { Content = content });
        }

        public Task<ApiResponse<SubmitAiArgumentResponse>> AiSubmitsAsync(
            int sessionId, int? turnIndex, string? content = "AI speech", int userId = UserA)
        {
            return NewService().SubmitAiArgumentAsync(userId, sessionId, new SubmitAiArgumentRequest { Content = content, TurnIndex = turnIndex });
        }

        public int ArgumentCount(int sessionId)
        {
            using var context = CreateContext();
            return context.Arguments.Count(a => context.DebateRounds.Any(r => r.RoundId == a.RoundId && r.DebateSessionId == sessionId));
        }

        public DebateSession LoadSession(int sessionId)
        {
            using var context = CreateContext();
            return context.DebateSessions
                .Include(s => s.DebateRounds)
                .AsNoTracking()
                .Single(s => s.DebateSessionId == sessionId);
        }

        public void Dispose()
        {
            // A background evaluation may still run (last turn submitted, nobody awaited it): let it end first
            for (int i = 0; i < 500 && _coordinator?.HasRunningEvaluations == true; i++)
            {
                Thread.Sleep(20);
            }
            _provider?.Dispose();
            lock (_contexts)
            {
                foreach (var context in _contexts)
                {
                    context.Dispose();
                }
            }
        }
    }

    internal static class ApiResponseAssert
    {
        public static void FailsWith<T>(ApiResponse<T> response, string expectedCode)
        {
            Assert.False(response.Success, "Expected failure but got success: " + response.Message);
            var detail = Assert.IsType<ApiErrorDetail>(response.Errors);
            Assert.Equal(expectedCode, detail.Code);
        }

        public static T Succeeds<T>(ApiResponse<T> response)
        {
            Assert.True(response.Success, response.Message);
            Assert.NotNull(response.Data);
            return response.Data!;
        }
    }
}
