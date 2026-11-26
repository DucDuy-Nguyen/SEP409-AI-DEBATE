using System;
using System.Collections.Generic;
using System.Linq;
using System.Security.Claims;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Diagnostics;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging.Abstractions;
using PayOS.Models.Webhooks;
using SystemService.BLL.Common.Payment;
using SystemService.BLL.Common.Responses;
using SystemService.BLL.DTOs.AI;
using SystemService.BLL.DTOs.Competition.Management;
using SystemService.BLL.DTOs.Competition.Team;
using SystemService.BLL.DTOs.Debate;
using SystemService.BLL.DTOs.Payment;
using SystemService.BLL.Services.AI.Interfaces;
using SystemService.BLL.Services.Competition.Implementations;
using SystemService.BLL.Services.Debate.Implementations;
using SystemService.BLL.Services.Payment.Implementations;
using SystemService.BLL.Services.Payment.Interfaces;
using SystemService.Controllers.Competition;
using SystemService.Controllers.Debate;
using SystemService.Controllers.Payment;
using SystemService.DAL.Context;
using SystemService.DAL.Entities.Competition;
using SystemService.DAL.Entities.Debate;
using SystemService.DAL.Entities.Debate.Enums;
using SystemService.DAL.Entities.Identity;
using SystemService.DAL.Entities.Payment;
using SystemService.DAL.Repositories.Competition.Implementations;
using SystemService.DAL.Repositories.Debate.Implementations;
using SystemService.DAL.Repositories.Identity.Implementations;
using SystemService.DAL.Repositories.Payment.Implementations;

namespace SystemService.Tests.Payment
{
    public class CreditSystemTests : IDisposable
    {
        private readonly string _dbName = $"CreditTests_{Guid.NewGuid():N}";
        private readonly List<SystemDbContext> _contexts = new();
        private ServiceProvider? _evalProvider;
        private DebateEvaluationCoordinator? _coordinator;
        private IAiEvaluatorClient? _lastEvaluator;

        private const int LecturerId = 1;
        private const int Member1Id = 2;
        private const int Member2Id = 3;
        private const int Member3Id = 4;
        private const int Member4Id = 5;

        public CreditSystemTests()
        {
            using var ctx = CreateContext();

            var adminRole = new Role { RoleId = 1, RoleName = "Admin" };
            var lecturerRole = new Role { RoleId = 2, RoleName = "Lecturer" };
            var memberRole = new Role { RoleId = 3, RoleName = "Member" };
            ctx.Roles.AddRange(adminRole, lecturerRole, memberRole);

            var lecturer = new User { UserId = LecturerId, FullName = "Lecturer", Email = "lec@test.local", IsActive = true };
            var m1 = new User { UserId = Member1Id, FullName = "Member 1", Email = "m1@test.local", IsActive = true };
            var m2 = new User { UserId = Member2Id, FullName = "Member 2", Email = "m2@test.local", IsActive = true };
            var m3 = new User { UserId = Member3Id, FullName = "Member 3", Email = "m3@test.local", IsActive = true };
            var m4 = new User { UserId = Member4Id, FullName = "Member 4", Email = "m4@test.local", IsActive = true };
            ctx.Users.AddRange(lecturer, m1, m2, m3, m4);

            ctx.UserRoles.AddRange(
                new UserRole { UserId = LecturerId, RoleId = 2 },
                new UserRole { UserId = Member1Id, RoleId = 3 },
                new UserRole { UserId = Member2Id, RoleId = 3 },
                new UserRole { UserId = Member3Id, RoleId = 3 },
                new UserRole { UserId = Member4Id, RoleId = 3 });

            ctx.DebateFormats.AddRange(
                new DebateFormat { FormatId = 1, FormatName = "User vs AI", MaxParticipants = 2, TotalRounds = 3, RoundDurationSeconds = 180, IsActive = true },
                new DebateFormat { FormatId = 2, FormatName = "1 vs 1", MaxParticipants = 2, TotalRounds = 3, RoundDurationSeconds = 180, IsActive = true },
                new DebateFormat { FormatId = 3, FormatName = "2 vs 2", MaxParticipants = 4, TotalRounds = 3, RoundDurationSeconds = 180, IsActive = true });

            ctx.Topics.Add(new Topic
            {
                TopicId = 1,
                Title = "AI in Education",
                Description = "AI should assist teachers in classrooms",
                Category = "education",
                Difficulty = "Medium",
                IsActive = true
            });

            ctx.CreditRules.AddRange(
                new CreditRule { RuleCode = CreditRuleCodes.AiPracticeMatch, CreditAmount = 150, Description = "AI Practice RAG", IsActive = true },
                new CreditRule { RuleCode = CreditRuleCodes.AiPracticeNoRag, CreditAmount = 110, Description = "AI Practice No RAG", IsActive = true },
                new CreditRule { RuleCode = CreditRuleCodes.AiHint, CreditAmount = 5, Description = "AI Hint", IsActive = true },
                new CreditRule { RuleCode = CreditRuleCodes.CompetitionSmall, CreditAmount = 500, Description = "Small Comp", IsActive = true },
                new CreditRule { RuleCode = CreditRuleCodes.CompetitionMedium, CreditAmount = 1200, Description = "Medium Comp", IsActive = true },
                new CreditRule { RuleCode = CreditRuleCodes.CompetitionLarge, CreditAmount = 2500, Description = "Large Comp", IsActive = true },
                new CreditRule { RuleCode = CreditRuleCodes.P2pMatchPerUser, CreditAmount = 40, Description = "Legacy disabled", IsActive = false },
                new CreditRule { RuleCode = CreditRuleCodes.DailyLogin, CreditAmount = 20, Description = "Daily Login", IsActive = true },
                new CreditRule { RuleCode = CreditRuleCodes.FirstLogin, CreditAmount = 200, Description = "First Login", IsActive = true },
                new CreditRule { RuleCode = CreditRuleCodes.CustomTopUpUnitPriceVnd, CreditAmount = 12, Description = "Custom Top-Up VND/Credit", IsActive = true });

            ctx.CreditPackages.AddRange(
                new CreditPackage { PackageId = 1, PackageCode = "BASIC", PackageName = "Basic", Price = 20000m, Currency = "VND", CreditAmount = 2000, BonusCredit = 0, IsActive = true },
                new CreditPackage { PackageId = 2, PackageCode = "STANDARD", PackageName = "Standard", Price = 50000m, Currency = "VND", CreditAmount = 5200, BonusCredit = 0, IsActive = true },
                new CreditPackage { PackageId = 3, PackageCode = "PREMIUM", PackageName = "Premium", Price = 100000m, Currency = "VND", CreditAmount = 11000, BonusCredit = 0, IsActive = true });

            ctx.Wallets.AddRange(
                new Wallet { UserId = LecturerId, Balance = 5000 },
                new Wallet { UserId = Member1Id, Balance = 300 },
                new Wallet { UserId = Member2Id, Balance = 0 },
                new Wallet { UserId = Member3Id, Balance = 0 },
                new Wallet { UserId = Member4Id, Balance = 0 });

            ctx.SaveChanges();
        }

        private SystemDbContext CreateContext()
        {
            var options = new DbContextOptionsBuilder<SystemDbContext>()
                .UseInMemoryDatabase(_dbName)
                .ConfigureWarnings(w => w.Ignore(InMemoryEventId.TransactionIgnoredWarning))
                .Options;
            var ctx = new SystemDbContext(options);
            _contexts.Add(ctx);
            return ctx;
        }

        public void Dispose()
        {
            if (_coordinator != null)
            {
                for (int i = 0; i < 200 && _coordinator.HasRunningEvaluations; i++)
                {
                    Thread.Sleep(20);
                }
            }
            _evalProvider?.Dispose();
            foreach (var c in _contexts) c.Dispose();
        }

        private void SetBalance(int userId, long balance)
        {
            using var ctx = CreateContext();
            var wallet = ctx.Wallets.Single(w => w.UserId == userId);
            wallet.Balance = balance;
            ctx.SaveChanges();
        }

        private long GetBalance(int userId)
        {
            using var ctx = CreateContext();
            return ctx.Wallets.AsNoTracking().Single(w => w.UserId == userId).Balance;
        }

        private List<WalletTransaction> GetTransactions(int userId)
        {
            using var ctx = CreateContext();
            var walletId = ctx.Wallets.AsNoTracking().Single(w => w.UserId == userId).WalletId;
            return ctx.WalletTransactions.AsNoTracking()
                .Where(wt => wt.WalletId == walletId)
                .OrderBy(wt => wt.WalletTransactionId)
                .ToList();
        }

        private void EndPreparation(SystemDbContext ctx, int sessionId)
        {
            var now = DateTime.UtcNow;
            var rounds = ctx.DebateRounds
                .Where(r => r.DebateSessionId == sessionId && r.StartTime != null && r.StartTime > now)
                .ToList();
            if (rounds.Count == 0) return;
            foreach (var round in rounds)
            {
                round.StartTime = now.AddSeconds(-1);
            }
            ctx.SaveChanges();
        }

        private CreditService NewCreditService(SystemDbContext ctx, IAiEvaluatorClient? evaluator = null)
        {
            return new CreditService(
                ctx,
                new RewardRepository(ctx),
                new WalletRepository(ctx),
                new DebateRepository(ctx),
                evaluator ?? new FakeAiEvaluatorClient());
        }

        private DebateEvaluationCoordinator GetCoordinator()
        {
            if (_coordinator == null)
            {
                var services = new ServiceCollection();
                services.AddScoped<SystemService.BLL.Services.Debate.Interfaces.IDebateService>(_ =>
                {
                    var evalCtx = CreateContext();
                    return new DebateService(
                        new DebateRepository(evalCtx),
                        new UserRepository(evalCtx),
                        _lastEvaluator ?? new FakeAiEvaluatorClient(),
                        evaluationCoordinator: _coordinator,
                        walletRepository: new WalletRepository(evalCtx),
                        creditService: NewCreditService(evalCtx, _lastEvaluator));
                });
                _evalProvider = services.BuildServiceProvider();
                _coordinator = new DebateEvaluationCoordinator(_evalProvider.GetRequiredService<IServiceScopeFactory>());
            }
            return _coordinator;
        }

        private DebateService NewDebateService(SystemDbContext ctx, IAiEvaluatorClient? evaluator = null)
        {
            _lastEvaluator = evaluator ?? new FakeAiEvaluatorClient();
            return new DebateService(
                new DebateRepository(ctx),
                new UserRepository(ctx),
                _lastEvaluator,
                evaluationCoordinator: GetCoordinator(),
                walletRepository: new WalletRepository(ctx),
                creditService: NewCreditService(ctx, _lastEvaluator));
        }

        private CompetitionService NewCompetitionService(SystemDbContext ctx)
        {
            return new CompetitionService(
                new CompetitionRepository(ctx),
                new DebateFormatRepository(ctx),
                new UserRepository(ctx),
                new CompetitionRegistrationRepository(ctx),
                new CompetitionTeamRepository(ctx),
                new WalletRepository(ctx),
                NewCreditService(ctx),
                ctx);
        }

        // ============================================================
        // TASK A & F: CreditRules & FE Price Endpoints
        // ============================================================

        [Fact]
        public async Task GetPrices_ReturnsExactCentralizedPricing_AndFreeFeatures()
        {
            using var ctx = CreateContext();
            var controller = new CreditsController(NewCreditService(ctx));

            var actionResult = await controller.GetPrices(CancellationToken.None);
            var ok = Assert.IsType<OkObjectResult>(actionResult);
            var res = Assert.IsType<ApiResponse<CreditPricesResponse>>(ok.Value);

            Assert.True(res.Success);
            Assert.Equal(150, res.Data!.AiPracticeRag);
            Assert.Equal(110, res.Data.AiPracticeNoRag);
            Assert.Equal(5, res.Data.AiHint);
            Assert.Equal(500, res.Data.CompetitionSmall);
            Assert.Equal(1200, res.Data.CompetitionMedium);
            Assert.Equal(2500, res.Data.CompetitionLarge);
            Assert.Equal(0, res.Data.P2p1v1);
            Assert.Equal(0, res.Data.P2p2v2);
            Assert.Equal(0, res.Data.CompetitionJoin);
            Assert.Equal(0, res.Data.AiEvaluatorP2p);
            Assert.Equal(12m, res.Data.CustomTopUpUnitPriceVnd);
            Assert.Equal(100, res.Data.CustomTopUpMinCredits);
            Assert.Equal(100000, res.Data.CustomTopUpMaxCredits);
        }

        [Fact]
        public async Task GetRulePrice_NeverChargesLegacyP2pRule_EvenIfActiveInDb()
        {
            using (var setup = CreateContext())
            {
                var p2pRule = setup.CreditRules.Single(r => r.RuleCode == CreditRuleCodes.P2pMatchPerUser);
                p2pRule.IsActive = true;
                setup.SaveChanges();
            }

            using var ctx = CreateContext();
            var service = NewCreditService(ctx);
            Assert.Equal(0, await service.GetRulePriceAsync(CreditRuleCodes.P2pMatchPerUser));
        }

        [Theory]
        [InlineData("INDIVIDUAL", 8, null, "SMALL", 500)]
        [InlineData("INDIVIDUAL", 16, null, "MEDIUM", 1200)]
        [InlineData("INDIVIDUAL", 32, null, "LARGE", 2500)]
        [InlineData("TEAM", 8, null, "SMALL", 500)]
        [InlineData("TEAM", null, 4, "SMALL", 500)]
        [InlineData("TEAM", null, 8, "MEDIUM", 1200)]
        [InlineData("TEAM", 32, null, "LARGE", 2500)]
        [InlineData("TEAM", null, 16, "LARGE", 2500)]
        public async Task GetCompetitionPrice_ReturnsExpectedScaleAndPrice(
            string type, int? maxParticipants, int? maxTeams, string expectedScale, long expectedCredits)
        {
            using var ctx = CreateContext();
            var controller = new CreditsController(NewCreditService(ctx));

            var actionResult = await controller.GetCompetitionPrice(type, maxParticipants, maxTeams, CancellationToken.None);
            var ok = Assert.IsType<OkObjectResult>(actionResult);
            var res = Assert.IsType<ApiResponse<CompetitionPriceQuoteResponse>>(ok.Value);

            Assert.True(res.Success);
            Assert.Equal(expectedScale, res.Data!.Scale);
            Assert.Equal(expectedCredits, res.Data.RequiredCredits);
        }

        [Theory]
        [InlineData("INDIVIDUAL", 33, null)]
        [InlineData("TEAM", 34, null)]
        [InlineData("TEAM", null, 17)]
        [InlineData("TEAM", 5, null)]
        public async Task GetCompetitionPrice_RejectsAboveLargeOrOddTeam(string type, int? maxParticipants, int? maxTeams)
        {
            using var ctx = CreateContext();
            var service = NewCreditService(ctx);
            var res = await service.GetCompetitionPriceQuoteAsync(type, maxParticipants, maxTeams);
            Assert.False(res.Success);
        }

        // ============================================================
        // FREE FLOWS: P2P 1v1, P2P 2v2, AcceptChallenge, Evaluator, Competition Participant
        // ============================================================

        [Fact]
        public async Task FreeFlows_P2p1v1_AcceptChallenge_AiEvaluation_CostZeroCredits()
        {
            SetBalance(Member1Id, 0);
            SetBalance(Member2Id, 0);

            int sessionId;
            using (var ctx = CreateContext())
            {
                var debateService = NewDebateService(ctx);
                var created = await debateService.CreateP2pSessionAsync(Member1Id, new CreateP2pSessionRequest
                {
                    TopicId = 1, Title = "t", Topic = "t", UserSide = DebateSide.PRO, IsAI = false
                });
                Assert.True(created.Success, created.Message);
                sessionId = created.Data!.SessionId;

                var joined = await debateService.JoinP2pSessionAsync(Member2Id, sessionId, new JoinSessionRequest());
                Assert.True(joined.Success, joined.Message);

                var started = await debateService.StartDebateSessionAsync(Member1Id, sessionId);
                Assert.True(started.Success, started.Message);

                EndPreparation(ctx, sessionId);
                Assert.True((await debateService.SubmitArgumentAsync(Member1Id, sessionId, new SubmitArgumentRequest { Content = "PRO 1" })).Success);
                Assert.True((await debateService.SubmitArgumentAsync(Member2Id, sessionId, new SubmitArgumentRequest { Content = "CON 1" })).Success);
                EndPreparation(ctx, sessionId);
                Assert.True((await debateService.SubmitArgumentAsync(Member1Id, sessionId, new SubmitArgumentRequest { Content = "PRO 2" })).Success);
                Assert.True((await debateService.SubmitArgumentAsync(Member2Id, sessionId, new SubmitArgumentRequest { Content = "CON 2" })).Success);
                EndPreparation(ctx, sessionId);
                Assert.True((await debateService.SubmitArgumentAsync(Member2Id, sessionId, new SubmitArgumentRequest { Content = "CON 3" })).Success);
                Assert.True((await debateService.SubmitArgumentAsync(Member1Id, sessionId, new SubmitArgumentRequest { Content = "PRO 3" })).Success);

                var eval = await debateService.EvaluateSessionAsync(Member1Id, sessionId);
                Assert.True(eval.Success, eval.Message);
            }

            // AcceptChallenge is also free
            using (var ctx2 = CreateContext())
            {
                var challengeService = new DebateChallengeService(
                    new DebateChallengeRepository(ctx2),
                    new DebateRepository(ctx2),
                    new UserRepository(ctx2));
                var ch = await challengeService.CreateChallengeAsync(Member1Id, new CreateChallengeRequest
                {
                    ChallengedUserId = Member2Id,
                    TopicId = 1,
                    ChallengerPreferredSide = DebateSide.PRO
                });
                Assert.True(ch.Success, ch.Message);
                var accepted = await challengeService.AcceptChallengeAsync(Member2Id, ch.Data!.ChallengeId);
                Assert.True(accepted.Success, accepted.Message);
            }

            Assert.Equal(0, GetBalance(Member1Id));
            Assert.Equal(0, GetBalance(Member2Id));
            Assert.Empty(GetTransactions(Member1Id));
            Assert.Empty(GetTransactions(Member2Id));
        }

        [Fact]
        public async Task FreeFlows_P2p2v2_CostsZeroCredits()
        {
            SetBalance(Member1Id, 0);
            SetBalance(Member2Id, 0);
            SetBalance(Member3Id, 0);
            SetBalance(Member4Id, 0);

            using var ctx = CreateContext();
            var debateService = NewDebateService(ctx);
            var created = await debateService.Create2v2SessionAsync(Member1Id, new Create2v2SessionRequest
            {
                TopicId = 1, Title = "t", Topic = "t", UserSide = DebateSide.PRO, IsAI = false
            });
            Assert.True(created.Success, created.Message);
            int sid = created.Data!.SessionId;

            Assert.True((await debateService.Join2v2SessionAsync(Member2Id, sid, new Join2v2SessionRequest { PreferredSide = DebateSide.CON })).Success);
            Assert.True((await debateService.Join2v2SessionAsync(Member3Id, sid, new Join2v2SessionRequest { PreferredSide = DebateSide.PRO })).Success);
            Assert.True((await debateService.Join2v2SessionAsync(Member4Id, sid, new Join2v2SessionRequest { PreferredSide = DebateSide.CON })).Success);

            var started = await debateService.StartDebateSessionAsync(Member1Id, sid);
            Assert.True(started.Success, started.Message);
            Assert.Empty(GetTransactions(Member1Id));
        }

        [Fact]
        public async Task FreeFlows_CompetitionParticipantAndMatchStart_CostZeroCredits()
        {
            SetBalance(LecturerId, 2000);
            SetBalance(Member1Id, 0);
            SetBalance(Member2Id, 0);

            int compId;
            using (var ctx = CreateContext())
            {
                var compService = NewCompetitionService(ctx);
                var now = DateTime.UtcNow;
                var created = await compService.CreateAsync(LecturerId, new CreateCompetitionRequest
                {
                    Title = "Free Entry Comp",
                    CompetitionType = "INDIVIDUAL",
                    MaxParticipants = 8,
                    RegistrationStart = now.AddMinutes(-5),
                    RegistrationEnd = now.AddMinutes(10),
                    StartDate = now.AddMinutes(20)
                });
                Assert.True(created.Success, created.Message);
                compId = created.Data!.CompetitionId;
                Assert.Equal(500, created.Data.CreditsCharged);
                Assert.Equal(1500, GetBalance(LecturerId));

                // Publish Draft -> no second charge
                var opened = await compService.OpenRegistrationAsync(compId, LecturerId);
                Assert.True(opened.Success, opened.Message);
                Assert.Equal(1500, GetBalance(LecturerId));
            }

            // Participant registration is free (even with 0 credits)
            using (var ctx = CreateContext())
            {
                var regService = new CompetitionRegistrationService(
                    new CompetitionRegistrationRepository(ctx),
                    new CompetitionRepository(ctx));
                Assert.True((await regService.RegisterAsync(compId, Member1Id)).Success);
                Assert.True((await regService.RegisterAsync(compId, Member2Id)).Success);
            }

            // Preparing and starting a competition match does NOT charge Lecturer or participants
            using (var ctx = CreateContext())
            {
                var round = new CompetitionRound { CompetitionId = compId, RoundNumber = 1, RoundName = "R1", Status = "Ongoing" };
                ctx.CompetitionRounds.Add(round);
                await ctx.SaveChangesAsync();

                var match = new CompetitionMatch
                {
                    CompetitionId = compId,
                    CompetitionRoundId = round.CompetitionRoundId,
                    MatchNumber = 1,
                    BracketPosition = 1,
                    Status = "Ready",
                    RowVersion = new byte[8]
                };
                match.Participants.Add(new MatchParticipant { UserId = Member1Id, Side = "PRO" });
                match.Participants.Add(new MatchParticipant { UserId = Member2Id, Side = "CON" });
                ctx.CompetitionMatches.Add(match);
                await ctx.SaveChangesAsync();

                var bridge = new CompetitionDebateBridgeService(ctx, new DebateRepository(ctx), new CompetitionTeamRepository(ctx));
                var prep = await bridge.PrepareMatchDebateAsync(LecturerId, match.CompetitionMatchId, 1);
                Assert.True(prep.Success, prep.Message);

                var debateService = NewDebateService(ctx);
                var started = await debateService.StartDebateSessionAsync(LecturerId, prep.Data!.SessionId);
                Assert.True(started.Success, started.Message);
            }

            Assert.Equal(1500, GetBalance(LecturerId));
            Assert.Equal(0, GetBalance(Member1Id));
            Assert.Equal(0, GetBalance(Member2Id));
        }

        // ============================================================
        // TASK C: AI Practice
        // ============================================================

        [Fact]
        public async Task AiPractice_WaitingRoomFree_StartCharges150_RetryDoesNotDoubleCharge_TurnsAndEvalFree()
        {
            SetBalance(Member1Id, 300);

            int sessionId;
            using (var ctx = CreateContext())
            {
                var debateService = NewDebateService(ctx);
                var created = await debateService.CreateAiPracticeSessionAsync(Member1Id, new CreateAiPracticeSessionRequest
                {
                    TopicId = 1, Title = "AI", Topic = "AI", UserSide = DebateSide.PRO, IsAI = true
                });
                Assert.True(created.Success, created.Message);
                sessionId = created.Data!.SessionId;
            }

            // Waiting room did not deduct credit
            Assert.Equal(300, GetBalance(Member1Id));

            // Start session -> deducts 150
            using (var ctx = CreateContext())
            {
                var started = await NewDebateService(ctx).StartDebateSessionAsync(Member1Id, sessionId);
                Assert.True(started.Success, started.Message);
            }
            Assert.Equal(150, GetBalance(Member1Id));
            Assert.Single(GetTransactions(Member1Id));

            // Retry Start -> rejected because already InProgress, no second deduction
            using (var ctx = CreateContext())
            {
                var retry = await NewDebateService(ctx).StartDebateSessionAsync(Member1Id, sessionId);
                Assert.False(retry.Success);
            }
            Assert.Equal(150, GetBalance(Member1Id));
            Assert.Single(GetTransactions(Member1Id));

            // AI opponent turns + AI evaluation -> 0 extra charge
            using (var ctx = CreateContext())
            {
                var debateService = NewDebateService(ctx);
                EndPreparation(ctx, sessionId);
                Assert.True((await debateService.SubmitArgumentAsync(Member1Id, sessionId, new SubmitArgumentRequest { Content = "U1" })).Success);
                Assert.True((await debateService.SubmitAiArgumentAsync(Member1Id, sessionId, new SubmitAiArgumentRequest { TurnIndex = 1, Content = "A1" })).Success);
                EndPreparation(ctx, sessionId);
                Assert.True((await debateService.SubmitArgumentAsync(Member1Id, sessionId, new SubmitArgumentRequest { Content = "U2" })).Success);
                Assert.True((await debateService.SubmitAiArgumentAsync(Member1Id, sessionId, new SubmitAiArgumentRequest { TurnIndex = 3, Content = "A2" })).Success);
                Assert.True((await debateService.SubmitAiArgumentAsync(Member1Id, sessionId, new SubmitAiArgumentRequest { TurnIndex = 4, Content = "A3" })).Success);
                EndPreparation(ctx, sessionId);
                Assert.True((await debateService.SubmitArgumentAsync(Member1Id, sessionId, new SubmitArgumentRequest { Content = "U3" })).Success);
                Assert.True((await debateService.EvaluateSessionAsync(Member1Id, sessionId)).Success);
            }
            Assert.Equal(150, GetBalance(Member1Id));
        }

        [Fact]
        public async Task AiPractice_InsufficientCredits_RejectedWithDetails_AndSessionRemainsWaiting()
        {
            SetBalance(Member1Id, 100);

            int sessionId;
            using (var ctx = CreateContext())
            {
                var created = await NewDebateService(ctx).CreateAiPracticeSessionAsync(Member1Id, new CreateAiPracticeSessionRequest
                {
                    TopicId = 1, Title = "AI", Topic = "AI", UserSide = DebateSide.PRO, IsAI = true
                });
                sessionId = created.Data!.SessionId;
            }

            using (var ctx = CreateContext())
            {
                var controller = CreateDebateController(NewDebateService(ctx), Member1Id);
                var action = await controller.StartDebateSession(sessionId, CancellationToken.None);
                var bad = Assert.IsType<BadRequestObjectResult>(action);
                var payload = Assert.IsType<ApiResponse<InsufficientCreditsData>>(bad.Value);

                Assert.False(payload.Success);
                Assert.Equal("INSUFFICIENT_CREDITS", payload.Code);
                Assert.Equal(150, payload.Data!.RequiredCredits);
                Assert.Equal(100, payload.Data.CurrentCredits);
                Assert.Equal(50, payload.Data.MissingCredits);
            }

            Assert.Equal(100, GetBalance(Member1Id));
            using (var ctx = CreateContext())
            {
                var s = ctx.DebateSessions.Single(x => x.DebateSessionId == sessionId);
                Assert.Equal(SessionStatus.Waiting, s.Status);
            }
        }

        [Fact]
        public async Task AiPractice_NoRag_Charges110_AndDisablesEvidenceCheck_AndLegacyDefaultsTo150()
        {
            // Case 1: EnableRag = false -> Charges 110
            SetBalance(Member1Id, 200);

            int noRagSessionId;
            using (var ctx = CreateContext())
            {
                var created = await NewDebateService(ctx).CreateAiPracticeSessionAsync(Member1Id, new CreateAiPracticeSessionRequest
                {
                    TopicId = 1, Title = "AI No RAG", Topic = "AI No RAG", UserSide = DebateSide.PRO, IsAI = true, EnableRag = false
                });
                Assert.True(created.Success, created.Message);
                Assert.False(created.Data!.EnableRag);
                noRagSessionId = created.Data.SessionId;
            }

            var evaluator = new FakeAiEvaluatorClient();
            using (var ctx = CreateContext())
            {
                var debateService = NewDebateService(ctx, evaluator);
                var started = await debateService.StartDebateSessionAsync(Member1Id, noRagSessionId);
                Assert.True(started.Success, started.Message);

                // Run turns to completion
                EndPreparation(ctx, noRagSessionId);
                Assert.True((await debateService.SubmitArgumentAsync(Member1Id, noRagSessionId, new SubmitArgumentRequest { Content = "U1" })).Success);
                Assert.True((await debateService.SubmitAiArgumentAsync(Member1Id, noRagSessionId, new SubmitAiArgumentRequest { TurnIndex = 1, Content = "A1" })).Success);
                EndPreparation(ctx, noRagSessionId);
                Assert.True((await debateService.SubmitArgumentAsync(Member1Id, noRagSessionId, new SubmitArgumentRequest { Content = "U2" })).Success);
                Assert.True((await debateService.SubmitAiArgumentAsync(Member1Id, noRagSessionId, new SubmitAiArgumentRequest { TurnIndex = 3, Content = "A2" })).Success);
                Assert.True((await debateService.SubmitAiArgumentAsync(Member1Id, noRagSessionId, new SubmitAiArgumentRequest { TurnIndex = 4, Content = "A3" })).Success);
                EndPreparation(ctx, noRagSessionId);
                Assert.True((await debateService.SubmitArgumentAsync(Member1Id, noRagSessionId, new SubmitArgumentRequest { Content = "U3" })).Success);

                var evaluated = await debateService.EvaluateSessionAsync(Member1Id, noRagSessionId);
                Assert.True(evaluated.Success, evaluated.Message);
            }

            // Deducted exactly 110 credits: 200 - 110 = 90
            Assert.Equal(90, GetBalance(Member1Id));
            var noRagTx = Assert.Single(GetTransactions(Member1Id));
            Assert.Equal(110, noRagTx.Amount);
            Assert.Contains(CreditRuleCodes.AiPracticeNoRag, noRagTx.Description);

            // Verify AI Evaluator was called with Topic=null and CheckEvidence=false
            Assert.NotEmpty(evaluator.EvaluatedRounds);
            Assert.All(evaluator.EvaluatedRounds, r =>
            {
                Assert.False(r.CheckEvidence);
                Assert.Null(r.Topic);
            });

            // Case 2: Legacy request without EnableRag -> Defaults to RAG (150)
            SetBalance(Member2Id, 200);
            int legacySessionId;
            using (var ctx = CreateContext())
            {
                var created = await NewDebateService(ctx).CreateAiPracticeSessionAsync(Member2Id, new CreateAiPracticeSessionRequest
                {
                    TopicId = 1, Title = "Legacy AI", Topic = "Legacy AI", UserSide = DebateSide.PRO, IsAI = true, EnableRag = null
                });
                Assert.True(created.Success, created.Message);
                Assert.True(created.Data!.EnableRag);
                legacySessionId = created.Data.SessionId;
            }

            using (var ctx = CreateContext())
            {
                var started = await NewDebateService(ctx).StartDebateSessionAsync(Member2Id, legacySessionId);
                Assert.True(started.Success, started.Message);
            }

            // Deducted 150 credits: 200 - 150 = 50
            Assert.Equal(50, GetBalance(Member2Id));
            var legacyTx = Assert.Single(GetTransactions(Member2Id));
            Assert.Equal(150, legacyTx.Amount);
            Assert.Contains(CreditRuleCodes.AiPracticeMatch, legacyTx.Description);
        }

        [Fact]
        public async Task AiPractice_NoRag_InsufficientCredits_RejectedWith110Required()
        {
            SetBalance(Member1Id, 100);

            int sessionId;
            using (var ctx = CreateContext())
            {
                var created = await NewDebateService(ctx).CreateAiPracticeSessionAsync(Member1Id, new CreateAiPracticeSessionRequest
                {
                    TopicId = 1, Title = "AI No RAG", Topic = "AI No RAG", UserSide = DebateSide.PRO, IsAI = true, EnableRag = false
                });
                sessionId = created.Data!.SessionId;
            }

            using (var ctx = CreateContext())
            {
                var controller = CreateDebateController(NewDebateService(ctx), Member1Id);
                var action = await controller.StartDebateSession(sessionId, CancellationToken.None);
                var bad = Assert.IsType<BadRequestObjectResult>(action);
                var payload = Assert.IsType<ApiResponse<InsufficientCreditsData>>(bad.Value);

                Assert.False(payload.Success);
                Assert.Equal("INSUFFICIENT_CREDITS", payload.Code);
                Assert.Equal(110, payload.Data!.RequiredCredits);
                Assert.Equal(100, payload.Data.CurrentCredits);
                Assert.Equal(10, payload.Data.MissingCredits);
            }

            Assert.Equal(100, GetBalance(Member1Id));
        }

        // ============================================================
        // TASK D: AI Hint
        // ============================================================

        [Fact]
        public async Task AiHint_Charges5PerSuccess_SupportsP2p_IdempotentOnSameRequestId()
        {
            SetBalance(Member1Id, 150);

            int p2pSessionId;
            using (var ctx = CreateContext())
            {
                var debateService = NewDebateService(ctx);
                var created = await debateService.CreateP2pSessionAsync(Member1Id, new CreateP2pSessionRequest
                {
                    TopicId = 1, Title = "P2P", Topic = "P2P", UserSide = DebateSide.PRO, IsAI = false
                });
                p2pSessionId = created.Data!.SessionId;
                await debateService.JoinP2pSessionAsync(Member2Id, p2pSessionId, new JoinSessionRequest());
                await debateService.StartDebateSessionAsync(Member1Id, p2pSessionId);
            }

            // Call Hint 3 times with distinct requestIds -> 150 - 15 = 135
            for (int i = 1; i <= 3; i++)
            {
                using var ctx = CreateContext();
                var res = await NewCreditService(ctx).RequestArgumentHintAsync(Member1Id, new AiHintRequest
                {
                    SessionId = p2pSessionId,
                    DraftText = $"Draft argument {i}",
                    RequestId = $"hint-req-{i}-{Guid.NewGuid():N}"
                });
                Assert.True(res.Success, res.Message);
                Assert.Equal(5, res.Data!.CreditsCharged);
                Assert.False(res.Data.AlreadyProcessed);
            }
            Assert.Equal(135, GetBalance(Member1Id));

            // Retry with exact same requestId -> idempotent, still 135
            var retryReqId = $"hint-idemp-{Guid.NewGuid():N}";
            using (var ctx = CreateContext())
            {
                var first = await NewCreditService(ctx).RequestArgumentHintAsync(Member1Id, new AiHintRequest
                {
                    SessionId = p2pSessionId,
                    DraftText = "Retryable draft",
                    RequestId = retryReqId
                });
                Assert.True(first.Success, first.Message);
                Assert.False(first.Data!.AlreadyProcessed);
            }
            Assert.Equal(130, GetBalance(Member1Id));

            using (var ctx = CreateContext())
            {
                var second = await NewCreditService(ctx).RequestArgumentHintAsync(Member1Id, new AiHintRequest
                {
                    SessionId = p2pSessionId,
                    DraftText = "Retryable draft",
                    RequestId = retryReqId
                });
                Assert.True(second.Success, second.Message);
                Assert.True(second.Data!.AlreadyProcessed);
            }
            Assert.Equal(130, GetBalance(Member1Id));
        }

        [Fact]
        public async Task AiHint_AiFailureRefunds5Credits_OutsiderForbidden_InsufficientCreditsRejected()
        {
            SetBalance(Member1Id, 20);
            SetBalance(Member3Id, 100);

            int sessionId;
            using (var ctx = CreateContext())
            {
                var debateService = NewDebateService(ctx);
                var created = await debateService.CreateP2pSessionAsync(Member1Id, new CreateP2pSessionRequest
                {
                    TopicId = 1, Title = "P2P", Topic = "P2P", UserSide = DebateSide.PRO, IsAI = false
                });
                sessionId = created.Data!.SessionId;
                await debateService.JoinP2pSessionAsync(Member2Id, sessionId, new JoinSessionRequest());
                await debateService.StartDebateSessionAsync(Member1Id, sessionId);
            }

            // Outsider cannot call Hint on another user's session
            using (var ctx = CreateContext())
            {
                var controller = CreateCreditsController(NewCreditService(ctx), Member3Id);
                var action = await controller.RequestArgumentHint(new AiHintRequest
                {
                    SessionId = sessionId,
                    DraftText = "Spy draft",
                    RequestId = $"outsider-{Guid.NewGuid():N}"
                }, CancellationToken.None);
                var forbidden = Assert.IsType<ObjectResult>(action);
                Assert.Equal(StatusCodes.Status403Forbidden, forbidden.StatusCode);
            }
            Assert.Equal(100, GetBalance(Member3Id));

            // AI failure refunds deducted 5 Credits
            using (var ctx = CreateContext())
            {
                var failingEvaluator = new FakeAiEvaluatorClient { FailCoach = true };
                var res = await NewCreditService(ctx, failingEvaluator).RequestArgumentHintAsync(Member1Id, new AiHintRequest
                {
                    SessionId = sessionId,
                    DraftText = "Will fail AI",
                    RequestId = $"fail-{Guid.NewGuid():N}"
                });
                Assert.False(res.Success);
            }
            Assert.Equal(20, GetBalance(Member1Id));
            var txs = GetTransactions(Member1Id);
            Assert.Equal(2, txs.Count);
            Assert.Equal("Debit", txs[0].TransactionType);
            Assert.Equal("Credit", txs[1].TransactionType);
            Assert.Equal("Refund", txs[1].SourceType);

            // Insufficient credits (< 5) -> rejected without calling AI
            SetBalance(Member1Id, 3);
            using (var ctx = CreateContext())
            {
                var evaluator = new FakeAiEvaluatorClient();
                var controller = CreateCreditsController(NewCreditService(ctx, evaluator), Member1Id);
                var action = await controller.RequestArgumentHint(new AiHintRequest
                {
                    SessionId = sessionId,
                    DraftText = "Too poor",
                    RequestId = $"poor-{Guid.NewGuid():N}"
                }, CancellationToken.None);
                var bad = Assert.IsType<BadRequestObjectResult>(action);
                var payload = Assert.IsType<ApiResponse<InsufficientCreditsData>>(bad.Value);

                Assert.Equal("INSUFFICIENT_CREDITS", payload.Code);
                Assert.Equal(5, payload.Data!.RequiredCredits);
                Assert.Equal(3, payload.Data.CurrentCredits);
                Assert.Equal(2, payload.Data.MissingCredits);
                Assert.Equal(0, evaluator.Calls);
            }
        }

        [Fact]
        public async Task AiHint_SessionCompletedOrWaiting_RejectedWithoutDeductingCredits()
        {
            SetBalance(Member1Id, 50);

            int waitingSessionId;
            int completedSessionId;

            using (var ctx = CreateContext())
            {
                var debateService = NewDebateService(ctx);

                // Waiting session
                var waiting = await debateService.CreateP2pSessionAsync(Member1Id, new CreateP2pSessionRequest
                {
                    TopicId = 1, Title = "Waiting Session", Topic = "Topic", UserSide = DebateSide.PRO, IsAI = false
                });
                waitingSessionId = waiting.Data!.SessionId;

                // Completed session
                var completed = await debateService.CreateP2pSessionAsync(Member1Id, new CreateP2pSessionRequest
                {
                    TopicId = 1, Title = "Completed Session", Topic = "Topic", UserSide = DebateSide.PRO, IsAI = false
                });
                completedSessionId = completed.Data!.SessionId;
                await debateService.JoinP2pSessionAsync(Member2Id, completedSessionId, new JoinSessionRequest());
                await debateService.StartDebateSessionAsync(Member1Id, completedSessionId);

                EndPreparation(ctx, completedSessionId);
                await debateService.SubmitArgumentAsync(Member1Id, completedSessionId, new SubmitArgumentRequest { Content = "PRO 1" });
                await debateService.SubmitArgumentAsync(Member2Id, completedSessionId, new SubmitArgumentRequest { Content = "CON 1" });
                EndPreparation(ctx, completedSessionId);
                await debateService.SubmitArgumentAsync(Member1Id, completedSessionId, new SubmitArgumentRequest { Content = "PRO 2" });
                await debateService.SubmitArgumentAsync(Member2Id, completedSessionId, new SubmitArgumentRequest { Content = "CON 2" });
                EndPreparation(ctx, completedSessionId);
                await debateService.SubmitArgumentAsync(Member2Id, completedSessionId, new SubmitArgumentRequest { Content = "CON 3" });
                await debateService.SubmitArgumentAsync(Member1Id, completedSessionId, new SubmitArgumentRequest { Content = "PRO 3" });
                await debateService.EvaluateSessionAsync(Member1Id, completedSessionId);
            }

            // Attempt AI Hint on Waiting session -> Rejected "not started yet"
            using (var ctx = CreateContext())
            {
                var res = await NewCreditService(ctx).RequestArgumentHintAsync(Member1Id, new AiHintRequest
                {
                    SessionId = waitingSessionId,
                    DraftText = "Some draft argument",
                    RequestId = $"hint-waiting-{Guid.NewGuid():N}"
                });

                Assert.False(res.Success);
                Assert.Contains("not started", res.Message, StringComparison.OrdinalIgnoreCase);
            }

            // Attempt AI Hint on Completed session -> Rejected "already completed"
            using (var ctx = CreateContext())
            {
                var res = await NewCreditService(ctx).RequestArgumentHintAsync(Member1Id, new AiHintRequest
                {
                    SessionId = completedSessionId,
                    DraftText = "Some draft argument",
                    RequestId = $"hint-completed-{Guid.NewGuid():N}"
                });

                Assert.False(res.Success);
                Assert.Contains("already completed", res.Message, StringComparison.OrdinalIgnoreCase);
            }

            // Verify no credit was deducted
            Assert.Equal(50, GetBalance(Member1Id));
        }

        [Fact]
        public async Task AiHint_OrphanedDebitAfterServerCrash_IsAutoRefundedOnRetry()
        {
            SetBalance(Member1Id, 100);

            int sessionId;
            using (var ctx = CreateContext())
            {
                var created = await NewDebateService(ctx).CreateP2pSessionAsync(Member1Id, new CreateP2pSessionRequest
                {
                    TopicId = 1, Title = "Session", Topic = "Topic", UserSide = DebateSide.PRO, IsAI = false
                });
                sessionId = created.Data!.SessionId;
                await NewDebateService(ctx).JoinP2pSessionAsync(Member2Id, sessionId, new JoinSessionRequest());
                await NewDebateService(ctx).StartDebateSessionAsync(Member1Id, sessionId);
            }

            var orphanReqId = $"crash-req-{Guid.NewGuid():N}";
            var debitMarker = $"[HintReq:{orphanReqId}]";

            // Simulate server crash after debit: debit committed to DB 5 minutes ago, but process died before refund or completed cache
            using (var ctx = CreateContext())
            {
                var wallet = ctx.Wallets.Single(w => w.UserId == Member1Id);
                wallet.Balance -= 5;
                ctx.WalletTransactions.Add(new WalletTransaction
                {
                    WalletId = wallet.WalletId,
                    TransactionType = "Debit",
                    SourceType = "AiUsage",
                    Amount = 5,
                    BalanceBefore = 100,
                    BalanceAfter = 95,
                    ReferenceType = "AIHint",
                    ReferenceId = sessionId,
                    Description = $"AI Hint (AI_HINT) user #{Member1Id} session #{sessionId} {debitMarker}",
                    CreatedAt = DateTime.UtcNow.AddMinutes(-5)
                });
                ctx.SaveChanges();
            }
            Assert.Equal(95, GetBalance(Member1Id));

            // User retries with same requestId after server restart (empty in-memory cache)
            using (var ctx = CreateContext())
            {
                var res = await NewCreditService(ctx).RequestArgumentHintAsync(Member1Id, new AiHintRequest
                {
                    SessionId = sessionId,
                    DraftText = "Draft text",
                    RequestId = orphanReqId
                });

                // Auto-refunds the orphaned debit
                Assert.False(res.Success);
                Assert.Equal("ORPHANED_REQUEST_REFUNDED", res.Code);
            }

            // Balance is restored to 100
            Assert.Equal(100, GetBalance(Member1Id));

            // A refund transaction exists in database
            var txs = GetTransactions(Member1Id);
            Assert.Contains(txs, t => t.TransactionType == "Credit" && t.SourceType == "Refund" && t.Amount == 5);
        }

        // ============================================================
        // TASK B: Competition Creation, Upgrade, Downgrade, Cancel, Retry
        // ============================================================

        [Theory]
        [InlineData("INDIVIDUAL", 8, 500, "SMALL")]
        [InlineData("INDIVIDUAL", 16, 1200, "MEDIUM")]
        [InlineData("INDIVIDUAL", 32, 2500, "LARGE")]
        [InlineData("TEAM", 8, 500, "SMALL")]
        [InlineData("TEAM", 16, 1200, "MEDIUM")]
        [InlineData("TEAM", 32, 2500, "LARGE")]
        public async Task Competition_Create_ChargesCorrectScaleFee(
            string type, int maxParticipants, long expectedFee, string expectedScale)
        {
            SetBalance(LecturerId, 3000);

            using var ctx = CreateContext();
            var now = DateTime.UtcNow;
            var res = await NewCompetitionService(ctx).CreateAsync(LecturerId, new CreateCompetitionRequest
            {
                Title = $"Comp {expectedScale}",
                CompetitionType = type,
                MaxParticipants = maxParticipants,
                RegistrationStart = now.AddDays(1),
                RegistrationEnd = now.AddDays(2),
                StartDate = now.AddDays(3),
                RequestId = $"comp-{expectedScale}-{Guid.NewGuid():N}"
            });

            Assert.True(res.Success, res.Message);
            Assert.Equal(expectedScale, res.Data!.Scale);
            Assert.Equal(expectedFee, res.Data.CreditsCharged);
            Assert.Equal(3000 - expectedFee, res.Data.RemainingCredits);
            Assert.Equal(3000 - expectedFee, GetBalance(LecturerId));
        }

        [Fact]
        public async Task Competition_InsufficientCredits_DoesNotCreateCompetition()
        {
            SetBalance(LecturerId, 200);

            using (var ctx = CreateContext())
            {
                var controller = CreateCompetitionsController(NewCompetitionService(ctx), LecturerId);
                var now = DateTime.UtcNow;
                var action = await controller.Create(new CreateCompetitionRequest
                {
                    Title = "Too Expensive",
                    CompetitionType = "INDIVIDUAL",
                    MaxParticipants = 8,
                    RegistrationStart = now.AddDays(1),
                    RegistrationEnd = now.AddDays(2),
                    StartDate = now.AddDays(3)
                }, CancellationToken.None);

                var bad = Assert.IsType<BadRequestObjectResult>(action);
                var payload = Assert.IsType<ApiResponse<InsufficientCreditsData>>(bad.Value);
                Assert.Equal("INSUFFICIENT_CREDITS", payload.Code);
                Assert.Equal(500, payload.Data!.RequiredCredits);
                Assert.Equal(200, payload.Data.CurrentCredits);
                Assert.Equal(300, payload.Data.MissingCredits);
            }

            using (var verify = CreateContext())
            {
                Assert.Empty(verify.Competitions);
            }
            Assert.Equal(200, GetBalance(LecturerId));
        }

        [Fact]
        public async Task Competition_MemberWithEnoughCredits_CreatesCompetitionSuccessfully()
        {
            SetBalance(Member1Id, 1500);

            using (var ctx = CreateContext())
            {
                var compService = NewCompetitionService(ctx);
                var now = DateTime.UtcNow;
                var created = await compService.CreateAsync(Member1Id, new CreateCompetitionRequest
                {
                    Title = "Member Organized Comp",
                    CompetitionType = "INDIVIDUAL",
                    MaxParticipants = 8,
                    RegistrationStart = now.AddDays(1),
                    RegistrationEnd = now.AddDays(2),
                    StartDate = now.AddDays(3)
                });

                Assert.True(created.Success, created.Message);
                Assert.Equal(500, created.Data!.CreditsCharged);
                Assert.Equal(1000, created.Data.RemainingCredits);
                Assert.Equal(1000, GetBalance(Member1Id));
                Assert.Equal(Member1Id, created.Data.CreatedBy);
            }
        }

        [Fact]
        public async Task Competition_MemberWithInsufficientCredits_ReturnsInsufficientCredits()
        {
            SetBalance(Member1Id, 100);

            using (var ctx = CreateContext())
            {
                var controller = CreateCompetitionsController(NewCompetitionService(ctx), Member1Id);
                var now = DateTime.UtcNow;
                var action = await controller.Create(new CreateCompetitionRequest
                {
                    Title = "Member Comp Too Expensive",
                    CompetitionType = "INDIVIDUAL",
                    MaxParticipants = 8,
                    RegistrationStart = now.AddDays(1),
                    RegistrationEnd = now.AddDays(2),
                    StartDate = now.AddDays(3)
                }, CancellationToken.None);

                var bad = Assert.IsType<BadRequestObjectResult>(action);
                var payload = Assert.IsType<ApiResponse<InsufficientCreditsData>>(bad.Value);
                Assert.Equal("INSUFFICIENT_CREDITS", payload.Code);
                Assert.Equal(500, payload.Data!.RequiredCredits);
                Assert.Equal(100, payload.Data.CurrentCredits);
                Assert.Equal(400, payload.Data.MissingCredits);
            }
        }

        [Fact]
        public async Task Competition_UpgradeChargesDifference_DowngradeAndCancelDoNotRefund_RetryIdempotent()
        {
            SetBalance(LecturerId, 3000);
            var reqId = $"comp-retry-{Guid.NewGuid():N}";
            int compId;

            using (var ctx = CreateContext())
            {
                var svc = NewCompetitionService(ctx);
                var now = DateTime.UtcNow;
                var req = new CreateCompetitionRequest
                {
                    Title = "Upgradeable Comp",
                    CompetitionType = "INDIVIDUAL",
                    MaxParticipants = 8, // SMALL = 500
                    RegistrationStart = now.AddDays(1),
                    RegistrationEnd = now.AddDays(2),
                    StartDate = now.AddDays(3),
                    RequestId = reqId
                };

                var first = await svc.CreateAsync(LecturerId, req);
                Assert.True(first.Success, first.Message);
                compId = first.Data!.CompetitionId;

                // Retry with same RequestId -> no second comp, no second charge
                var retry = await svc.CreateAsync(LecturerId, req);
                Assert.True(retry.Success, retry.Message);
                Assert.Equal(compId, retry.Data!.CompetitionId);
            }
            Assert.Equal(2500, GetBalance(LecturerId));

            // Upgrade SMALL (500) -> MEDIUM (1200) => charges difference 700
            using (var ctx = CreateContext())
            {
                var upgraded = await NewCompetitionService(ctx).PatchAsync(compId, LecturerId, new PatchCompetitionRequest
                {
                    MaxParticipants = 16
                });
                Assert.True(upgraded.Success, upgraded.Message);
                Assert.Equal(700, upgraded.Data!.CreditsCharged);
                Assert.Equal("MEDIUM", upgraded.Data.Scale);
            }
            Assert.Equal(1800, GetBalance(LecturerId));

            // Downgrade MEDIUM -> SMALL => no auto refund
            using (var ctx = CreateContext())
            {
                var downgraded = await NewCompetitionService(ctx).PatchAsync(compId, LecturerId, new PatchCompetitionRequest
                {
                    MaxParticipants = 8
                });
                Assert.True(downgraded.Success, downgraded.Message);
                Assert.Equal(0, downgraded.Data!.CreditsCharged);
            }
            Assert.Equal(1800, GetBalance(LecturerId));

            // Cancel => no auto refund
            using (var ctx = CreateContext())
            {
                var cancelled = await NewCompetitionService(ctx).CancelCompetitionAsync(compId, LecturerId);
                Assert.True(cancelled.Success, cancelled.Message);
            }
            Assert.Equal(1800, GetBalance(LecturerId));
        }

        // ============================================================
        // TASK E: PayOS & CreditPackages
        // ============================================================

        [Theory]
        [InlineData(1, 20000, 2000)]
        [InlineData(2, 50000, 5200)]
        [InlineData(3, 100000, 11000)]
        public async Task PayOS_SuccessWebhook_CreditsExactPackageAmount_AndReplayIsIdempotent(
            int packageId, decimal expectedPrice, long expectedCredits)
        {
            SetBalance(Member1Id, 0);
            var fakeGateway = new FakePaymentGateway();

            long orderCode;
            using (var ctx = CreateContext())
            {
                var paymentService = NewPaymentService(ctx, fakeGateway);
                var link = await paymentService.CreateTopUpPaymentAsync(Member1Id, new TopUpRequest
                {
                    PackageId = packageId,
                    FrontendOrigin = "http://localhost:5173"
                });
                Assert.True(link.Success, link.Message);
                Assert.Equal(expectedPrice, link.Data!.Amount);
                Assert.Equal(expectedCredits, link.Data.CreditAmount);
                orderCode = link.Data.ProviderOrderCode;
            }

            fakeGateway.NextVerification = new WebhookVerificationResult
            {
                IsValid = true,
                OrderCode = orderCode,
                Amount = expectedPrice,
                Code = "00",
                Reference = $"PAYOS-{orderCode}"
            };

            // First webhook -> credits wallet
            using (var ctx = CreateContext())
            {
                var res1 = await NewPaymentService(ctx, fakeGateway).ProcessPayOSWebhookAsync(new Webhook());
                Assert.True(res1.Success, res1.Message);
            }
            Assert.Equal(expectedCredits, GetBalance(Member1Id));

            // Duplicate webhook -> idempotent, does NOT double credit
            using (var ctx = CreateContext())
            {
                var res2 = await NewPaymentService(ctx, fakeGateway).ProcessPayOSWebhookAsync(new Webhook());
                Assert.True(res2.Success, res2.Message);
            }
            Assert.Equal(expectedCredits, GetBalance(Member1Id));
            Assert.Single(GetTransactions(Member1Id));
        }

        [Fact]
        public async Task PayOS_FailedOrCancelledWebhook_DoesNotCreditWallet()
        {
            SetBalance(Member1Id, 100);
            var fakeGateway = new FakePaymentGateway();

            long orderCode;
            using (var ctx = CreateContext())
            {
                var link = await NewPaymentService(ctx, fakeGateway).CreateTopUpPaymentAsync(Member1Id, new TopUpRequest
                {
                    PackageId = 1,
                    FrontendOrigin = "http://localhost:5173"
                });
                orderCode = link.Data!.ProviderOrderCode;
            }

            fakeGateway.NextVerification = new WebhookVerificationResult
            {
                IsValid = true,
                OrderCode = orderCode,
                Amount = 20000m,
                Code = "01", // non-success code
                Reference = "FAILED-REF"
            };

            using (var ctx = CreateContext())
            {
                var res = await NewPaymentService(ctx, fakeGateway).ProcessPayOSWebhookAsync(new Webhook());
                Assert.False(res.Success);
            }
            Assert.Equal(100, GetBalance(Member1Id));
            Assert.Empty(GetTransactions(Member1Id));
        }

        [Theory]
        [InlineData(100, 1200)]
        [InlineData(750, 9000)]
        [InlineData(2000, 24000)]
        public async Task CustomTopUp_QuoteCreateAndWebhook_CalculatesExactVnd_AndCreditsWalletOnce(
            long creditAmount, decimal expectedVnd)
        {
            SetBalance(Member1Id, 50);
            var fakeGateway = new FakePaymentGateway();

            long paymentId;
            long orderCode;
            using (var ctx = CreateContext())
            {
                var paymentService = NewPaymentService(ctx, fakeGateway);

                var quote = await paymentService.GetCustomTopUpQuoteAsync(creditAmount);
                Assert.True(quote.Success, quote.Message);
                Assert.Equal(12m, quote.Data!.UnitPriceVnd);
                Assert.Equal(expectedVnd, quote.Data.TotalAmountVnd);
                Assert.Equal(100, quote.Data.MinCredits);
                Assert.Equal(100000, quote.Data.MaxCredits);

                var created = await paymentService.CreateCustomTopUpPaymentAsync(Member1Id, new CustomTopUpRequest
                {
                    CreditAmount = creditAmount,
                    FrontendOrigin = "http://localhost:5173"
                });
                Assert.True(created.Success, created.Message);
                Assert.Equal(expectedVnd, created.Data!.Amount);
                Assert.Equal(creditAmount, created.Data.CreditAmount);
                Assert.Equal("Custom", created.Data.TopUpType);
                Assert.Equal(12m, created.Data.UnitPriceVnd);
                Assert.NotNull(created.Data.PaymentUrl);
                Assert.Equal(created.Data.CheckoutUrl, created.Data.PaymentUrl);

                paymentId = created.Data.PaymentId;
                orderCode = created.Data.ProviderOrderCode;

                var stored = await ctx.PaymentTransactions.SingleAsync(p => p.PaymentId == paymentId);
                Assert.Null(stored.PackageId);
                Assert.Equal("Pending", stored.Status);
            }

            fakeGateway.NextVerification = new WebhookVerificationResult
            {
                IsValid = true,
                OrderCode = orderCode,
                Amount = expectedVnd,
                Code = "00",
                Reference = $"PAYOS-CUSTOM-{orderCode}"
            };

            using (var ctx = CreateContext())
            {
                var settled = await NewPaymentService(ctx, fakeGateway).ProcessPayOSWebhookAsync(new Webhook());
                Assert.True(settled.Success, settled.Message);
            }
            Assert.Equal(50 + creditAmount, GetBalance(Member1Id));

            // Replay webhook does not double credit
            using (var ctx = CreateContext())
            {
                var replay = await NewPaymentService(ctx, fakeGateway).ProcessPayOSWebhookAsync(new Webhook());
                Assert.True(replay.Success, replay.Message);
            }
            Assert.Equal(50 + creditAmount, GetBalance(Member1Id));
            var tx = Assert.Single(GetTransactions(Member1Id));
            Assert.Equal(creditAmount, tx.Amount);

            using (var ctx = CreateContext())
            {
                var status = await NewPaymentService(ctx, fakeGateway).GetPaymentStatusAsync(Member1Id, paymentId);
                Assert.True(status.Success, status.Message);
                Assert.Equal("Custom", status.Data!.TopUpType);
                Assert.Equal("CUSTOM", status.Data.PackageCode);
                Assert.Equal("Paid", status.Data.Status);
                Assert.Equal(expectedVnd, status.Data.Amount);
                Assert.Equal(creditAmount, status.Data.CreditAmount);
            }
        }

        [Theory]
        [InlineData(0)]
        [InlineData(-50)]
        [InlineData(99)]
        [InlineData(100001)]
        public async Task CustomTopUp_InvalidCreditAmount_IsRejectedWithoutCreatingPayment(long invalidCredits)
        {
            var fakeGateway = new FakePaymentGateway();
            using var ctx = CreateContext();
            var paymentService = NewPaymentService(ctx, fakeGateway);

            var quote = await paymentService.GetCustomTopUpQuoteAsync(invalidCredits);
            Assert.False(quote.Success);

            var create = await paymentService.CreateCustomTopUpPaymentAsync(Member1Id, new CustomTopUpRequest
            {
                CreditAmount = invalidCredits,
                FrontendOrigin = "http://localhost:5173"
            });
            Assert.False(create.Success);
            Assert.Empty(ctx.PaymentTransactions);
        }

        [Fact]
        public async Task CustomTopUp_PriceSnapshotIsImmutableAfterRuleChange_AndSharesSingleWalletWithPackageTopUp()
        {
            SetBalance(Member1Id, 0);
            var fakeGateway = new FakePaymentGateway();

            long customOrderCode;
            long packageOrderCode;

            // Create 750 custom credits at 12 VND (= 9000 VND) and BASIC package (20000 VND -> 2000 credits)
            using (var ctx = CreateContext())
            {
                var paymentService = NewPaymentService(ctx, fakeGateway);

                var customController = CreatePaymentsController(paymentService, Member1Id);
                var quoteAction = await customController.GetCustomTopUpQuote(750, CancellationToken.None);
                var quoteOk = Assert.IsType<OkObjectResult>(quoteAction);
                var quoteRes = Assert.IsType<ApiResponse<CustomTopUpQuoteResponse>>(quoteOk.Value);
                Assert.Equal(9000m, quoteRes.Data!.TotalAmountVnd);

                var customAction = await customController.CreateCustomTopUpPayment(new CustomTopUpRequest { CreditAmount = 750 }, CancellationToken.None);
                var customOk = Assert.IsType<OkObjectResult>(customAction);
                var customRes = Assert.IsType<ApiResponse<PaymentLinkResponse>>(customOk.Value);
                Assert.Equal(9000m, customRes.Data!.Amount);
                customOrderCode = customRes.Data.ProviderOrderCode;

                var pkgRes = await paymentService.CreateTopUpPaymentAsync(Member1Id, new TopUpRequest
                {
                    PackageId = 1,
                    FrontendOrigin = "http://localhost:5173"
                });
                Assert.True(pkgRes.Success, pkgRes.Message);
                packageOrderCode = pkgRes.Data!.ProviderOrderCode;
            }

            // Admin updates custom unit price in DB to 20 VND AFTER pending order was created
            using (var ctx = CreateContext())
            {
                var rule = ctx.CreditRules.Single(r => r.RuleCode == CreditRuleCodes.CustomTopUpUnitPriceVnd);
                rule.CreditAmount = 20;
                ctx.SaveChanges();
            }

            // Webhook with mismatched amount (e.g. wrong price) is rejected
            fakeGateway.NextVerification = new WebhookVerificationResult
            {
                IsValid = true,
                OrderCode = customOrderCode,
                Amount = 15000m,
                Code = "00",
                Reference = "MISMATCH"
            };
            using (var ctx = CreateContext())
            {
                var badAmount = await NewPaymentService(ctx, fakeGateway).ProcessPayOSWebhookAsync(new Webhook());
                Assert.False(badAmount.Success);
            }

            // Webhook with original snapshot amount 9000 VND succeeds & credits 750
            fakeGateway.NextVerification = new WebhookVerificationResult
            {
                IsValid = true,
                OrderCode = customOrderCode,
                Amount = 9000m,
                Code = "00",
                Reference = "CUSTOM-OK"
            };
            using (var ctx = CreateContext())
            {
                Assert.True((await NewPaymentService(ctx, fakeGateway).ProcessPayOSWebhookAsync(new Webhook())).Success);
            }

            // Package payment settles into the EXACT SAME wallet
            fakeGateway.NextVerification = new WebhookVerificationResult
            {
                IsValid = true,
                OrderCode = packageOrderCode,
                Amount = 20000m,
                Code = "00",
                Reference = "PKG-OK"
            };
            using (var ctx = CreateContext())
            {
                Assert.True((await NewPaymentService(ctx, fakeGateway).ProcessPayOSWebhookAsync(new Webhook())).Success);
                Assert.Equal(1, await ctx.Wallets.CountAsync(w => w.UserId == Member1Id));
            }

            Assert.Equal(750 + 2000, GetBalance(Member1Id));
            Assert.Equal(2, GetTransactions(Member1Id).Count);
        }

        [Fact]
        public async Task CustomTopUp_FailedOrCancelledWebhook_DoesNotCreditWallet()
        {
            SetBalance(Member1Id, 100);
            var fakeGateway = new FakePaymentGateway();

            long orderCode;
            using (var ctx = CreateContext())
            {
                var res = await NewPaymentService(ctx, fakeGateway).CreateCustomTopUpPaymentAsync(Member1Id, new CustomTopUpRequest
                {
                    CreditAmount = 750,
                    FrontendOrigin = "http://localhost:5173"
                });
                Assert.True(res.Success, res.Message);
                orderCode = res.Data!.ProviderOrderCode;
            }

            fakeGateway.NextVerification = new WebhookVerificationResult
            {
                IsValid = true,
                OrderCode = orderCode,
                Amount = 9000m,
                Code = "01",
                Reference = "CUSTOM-FAIL"
            };
            using (var ctx = CreateContext())
            {
                var webhookRes = await NewPaymentService(ctx, fakeGateway).ProcessPayOSWebhookAsync(new Webhook());
                Assert.False(webhookRes.Success);
            }

            Assert.Equal(100, GetBalance(Member1Id));
            Assert.Empty(GetTransactions(Member1Id));
        }

        private PaymentService NewPaymentService(SystemDbContext ctx, IPaymentGateway gateway)
        {
            var config = new ConfigurationBuilder()
                .AddInMemoryCollection(new Dictionary<string, string?>
                {
                    ["PayOS:FrontendOrigin"] = "http://localhost:5173",
                    ["CustomTopUp:UnitPriceVnd"] = "12",
                    ["CustomTopUp:MinCredits"] = "100",
                    ["CustomTopUp:MaxCredits"] = "100000"
                })
                .Build();
            return new PaymentService(
                ctx,
                new WalletRepository(ctx),
                new CreditPackageRepository(ctx),
                new PaymentRepository(ctx),
                gateway,
                config,
                NullLogger<PaymentService>.Instance,
                new RewardRepository(ctx));
        }

        private static PaymentsController CreatePaymentsController(IPaymentService service, int userId)
        {
            return new PaymentsController(service)
            {
                ControllerContext = new ControllerContext
                {
                    HttpContext = new DefaultHttpContext
                    {
                        User = new ClaimsPrincipal(new ClaimsIdentity(
                            new[] { new Claim(ClaimTypes.NameIdentifier, userId.ToString()) }, "Test"))
                    }
                }
            };
        }

        private static CreditsController CreateCreditsController(ICreditService service, int userId)
        {
            return new CreditsController(service)
            {
                ControllerContext = new ControllerContext
                {
                    HttpContext = new DefaultHttpContext
                    {
                        User = new ClaimsPrincipal(new ClaimsIdentity(
                            new[] { new Claim(ClaimTypes.NameIdentifier, userId.ToString()) }, "Test"))
                    }
                }
            };
        }

        private static CompetitionsController CreateCompetitionsController(CompetitionService service, int userId)
        {
            return new CompetitionsController(service, null!)
            {
                ControllerContext = new ControllerContext
                {
                    HttpContext = new DefaultHttpContext
                    {
                        User = new ClaimsPrincipal(new ClaimsIdentity(
                            new[] { new Claim(ClaimTypes.NameIdentifier, userId.ToString()) }, "Test"))
                    }
                }
            };
        }

        private static DebateController CreateDebateController(DebateService service, int userId)
        {
            return new DebateController(service)
            {
                ControllerContext = new ControllerContext
                {
                    HttpContext = new DefaultHttpContext
                    {
                        User = new ClaimsPrincipal(new ClaimsIdentity(
                            new[] { new Claim(ClaimTypes.NameIdentifier, userId.ToString()) }, "Test"))
                    }
                }
            };
        }

        private sealed class FakeAiEvaluatorClient : IAiEvaluatorClient
        {
            public bool FailCoach { get; init; }
            public int Calls { get; private set; }
            public List<EvaluateRoundRequest> EvaluatedRounds { get; } = new();

            public Task<EvaluateArgumentResponse?> EvaluateArgumentAsync(EvaluateArgumentRequest req, CancellationToken ct = default)
            {
                Calls++;
                return Task.FromResult<EvaluateArgumentResponse?>(new EvaluateArgumentResponse(
                    OverallScore: 7.5m,
                    OverallReasoning: "Solid point",
                    Criteria: new List<CriterionScoreDto>
                    {
                        new("Logic", 4, "Good"),
                        new("Evidence", 3, "Needs stats"),
                        new("Relevance", 4, "On topic"),
                        new("Structure", 4, "Clear"),
                        new("Persuasiveness", 4, "Good")
                    },
                    Strengths: new List<string> { "Clear" },
                    Weaknesses: new List<string> { "Lack of evidence" },
                    Suggestions: new List<string> { "Add data" },
                    RawModelOutput: null));
            }

            public Task<CoachingResultDto?> CoachArgumentAsync(ArgumentCoachingRequest req, CancellationToken ct = default)
            {
                Calls++;
                if (FailCoach) throw new HttpRequestException("Simulated AI Coach 502 error");
                return Task.FromResult<CoachingResultDto?>(new CoachingResultDto(
                    FocusCriteria: new List<CriterionCoachingDto>
                    {
                        new("Evidence", 3, "Thiếu dẫn chứng", new List<string> { "Tìm số liệu từ báo cáo giáo dục" }, "Bổ sung số liệu vào luận điểm chính")
                    },
                    IdeaDevelopment: new IdeaDevelopmentDto("AI hỗ trợ giáo viên", new List<string> { "Giảm tải chấm bài", "Cá nhân hóa học tập" })));
            }

            public Task<EvaluateRoundResponse?> EvaluateRoundAsync(EvaluateRoundRequest req, CancellationToken ct = default)
            {
                EvaluatedRounds.Add(req);
                return Task.FromResult<EvaluateRoundResponse?>(new EvaluateRoundResponse(
                    req.Stage, 7.5m, new List<CriterionScoreDto> { new("Logic", 4, "Good") }, "Consistent",
                    new List<string>(), new List<string>(), new List<string>()));
            }

            public Task<EvaluateSessionResponse?> EvaluateSessionAsync(EvaluateSessionRequest req, CancellationToken ct = default) =>
                Task.FromResult<EvaluateSessionResponse?>(new EvaluateSessionResponse(
                    7.5m, new Dictionary<string, decimal> { ["opening"] = 7.5m }, "Stable",
                    new List<string>(), new List<string>(), new List<string>()));

            public Task<CoachingResultDto?> CoachRoundAsync(RoundCoachingRequest req, CancellationToken ct = default) =>
                throw new NotSupportedException();
        }

        private sealed class FakePaymentGateway : IPaymentGateway
        {
            public string ProviderName => "PayOS";
            public WebhookVerificationResult NextVerification { get; set; } = new() { IsValid = false };

            public Task<PaymentGatewayResult> CreatePaymentLinkAsync(PaymentLinkArgs args, CancellationToken cancellationToken = default)
            {
                return Task.FromResult(new PaymentGatewayResult
                {
                    Success = true,
                    CheckoutUrl = $"https://pay.payos.vn/web/{args.OrderCode}",
                    QrCode = $"QR-{args.OrderCode}"
                });
            }

            public Task<WebhookVerificationResult> VerifyWebhookAsync(Webhook webhook, CancellationToken cancellationToken = default)
            {
                return Task.FromResult(NextVerification);
            }
        }
    }
}
