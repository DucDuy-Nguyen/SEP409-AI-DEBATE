using System;
using System.Collections.Generic;
using System.Data;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Data.Sqlite;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Diagnostics;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging.Abstractions;
using PayOS.Models.Webhooks;
using SystemService.BLL.Common.Payment;
using SystemService.BLL.DTOs.Competition.Management;
using SystemService.BLL.DTOs.Debate;
using SystemService.BLL.DTOs.Payment;
using SystemService.BLL.Services.Competition.Implementations;
using SystemService.BLL.Services.Debate.Implementations;
using SystemService.BLL.Services.Payment.Implementations;
using SystemService.BLL.Services.Payment.Interfaces;
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
using Xunit;

namespace SystemService.IntegrationTests
{
    public class CreditTransactionIntegrationTests : IDisposable
    {
        private readonly SqliteConnection _connection;
        private readonly DbContextOptions<SystemDbContext> _options;

        public CreditTransactionIntegrationTests()
        {
            _connection = new SqliteConnection("DataSource=:memory:");
            _connection.Open();

            _options = new DbContextOptionsBuilder<SystemDbContext>()
                .UseSqlite(_connection)
                .Options;

            using var context = new TestSystemDbContext(_options);
            context.Database.EnsureCreated();
        }

        public void Dispose() => _connection.Dispose();

        private sealed class TestSystemDbContext : SystemDbContext
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

        private SystemDbContext CreateContext(params IInterceptor[] interceptors)
        {
            var builder = new DbContextOptionsBuilder<SystemDbContext>().UseSqlite(_connection);
            if (interceptors.Length > 0) builder.AddInterceptors(interceptors);
            return new TestSystemDbContext(builder.Options);
        }

        private async Task<(int lecturerId, int memberId)> SeedAsync()
        {
            using var ctx = CreateContext();
            var lecRole = new Role { RoleName = "Lecturer" };
            ctx.Roles.Add(lecRole);
            var lec = new User { FullName = "Lec", Email = $"lec_{Guid.NewGuid():N}@test.com", IsActive = true };
            var mem = new User { FullName = "Mem", Email = $"mem_{Guid.NewGuid():N}@test.com", IsActive = true };
            ctx.Users.AddRange(lec, mem);
            await ctx.SaveChangesAsync();

            ctx.UserRoles.Add(new UserRole { UserId = lec.UserId, RoleId = lecRole.RoleId });
            ctx.Wallets.AddRange(
                new Wallet { UserId = lec.UserId, Balance = 2000 },
                new Wallet { UserId = mem.UserId, Balance = 300 });
            ctx.CreditRules.AddRange(
                new CreditRule { RuleCode = CreditRuleCodes.AiPracticeMatch, CreditAmount = 150, IsActive = true },
                new CreditRule { RuleCode = CreditRuleCodes.CompetitionSmall, CreditAmount = 500, IsActive = true },
                new CreditRule { RuleCode = CreditRuleCodes.CompetitionMedium, CreditAmount = 1200, IsActive = true },
                new CreditRule { RuleCode = CreditRuleCodes.CompetitionLarge, CreditAmount = 2500, IsActive = true });
            ctx.CreditPackages.Add(new CreditPackage
            {
                PackageCode = "STANDARD", PackageName = "Standard", Price = 50000m, Currency = "VND", CreditAmount = 5200, BonusCredit = 0, IsActive = true
            });
            ctx.DebateFormats.Add(new DebateFormat { FormatName = "User vs AI", MaxParticipants = 2, TotalRounds = 3, RoundDurationSeconds = 180, IsActive = true });
            ctx.Topics.Add(new Topic { Title = "Topic", Description = "Desc", Category = "education", Difficulty = "Medium", IsActive = true });
            await ctx.SaveChangesAsync();
            return (lec.UserId, mem.UserId);
        }

        [Fact]
        public async Task CompetitionCreate_DatabaseFailure_RollsBackWalletAndCompetition()
        {
            var (lecturerId, _) = await SeedAsync();

            var failInterceptor = new FailOnWalletTransactionSaveInterceptor();
            using (var ctx = CreateContext(failInterceptor))
            {
                var creditService = new CreditService(ctx, new RewardRepository(ctx), new WalletRepository(ctx), new DebateRepository(ctx));
                var compService = new CompetitionService(
                    new CompetitionRepository(ctx),
                    new DebateFormatRepository(ctx),
                    new UserRepository(ctx),
                    new CompetitionRegistrationRepository(ctx),
                    new CompetitionTeamRepository(ctx),
                    new WalletRepository(ctx),
                    creditService,
                    ctx);

                var now = DateTime.UtcNow;
                await Assert.ThrowsAsync<InvalidOperationException>(() => compService.CreateAsync(lecturerId, new CreateCompetitionRequest
                {
                    Title = "Will Rollback",
                    CompetitionType = "INDIVIDUAL",
                    MaxParticipants = 8,
                    RegistrationStart = now.AddDays(1),
                    RegistrationEnd = now.AddDays(2),
                    StartDate = now.AddDays(3)
                }));
            }

            using var verify = CreateContext();
            Assert.Empty(await verify.Competitions.ToListAsync());
            Assert.Equal(2000, (await verify.Wallets.SingleAsync(w => w.UserId == lecturerId)).Balance);
            Assert.Empty(await verify.WalletTransactions.ToListAsync());
        }

        [Fact]
        public async Task AiPracticeStart_DatabaseFailure_RollsBackWalletAndSessionRemainsWaiting()
        {
            var (_, memberId) = await SeedAsync();

            int sessionId;
            using (var ctx = CreateContext())
            {
                var debateService = new DebateService(new DebateRepository(ctx), new UserRepository(ctx));
                var created = await debateService.CreateAiPracticeSessionAsync(memberId, new CreateAiPracticeSessionRequest
                {
                    TopicId = 1, Title = "AI", Topic = "AI", UserSide = DebateSide.PRO, IsAI = true
                });
                Assert.True(created.Success, created.Message);
                sessionId = created.Data!.SessionId;
            }

            var failInterceptor = new FailOnWalletTransactionSaveInterceptor();
            using (var ctx = CreateContext(failInterceptor))
            {
                var creditService = new CreditService(ctx, new RewardRepository(ctx), new WalletRepository(ctx), new DebateRepository(ctx));
                var debateService = new DebateService(
                    new DebateRepository(ctx),
                    new UserRepository(ctx),
                    walletRepository: new WalletRepository(ctx),
                    creditService: creditService);

                var res = await debateService.StartDebateSessionAsync(memberId, sessionId);
                Assert.False(res.Success);
            }

            using var verify = CreateContext();
            var session = await verify.DebateSessions.SingleAsync(s => s.DebateSessionId == sessionId);
            Assert.Equal(SessionStatus.Waiting, session.Status);
            Assert.Equal(300, (await verify.Wallets.SingleAsync(w => w.UserId == memberId)).Balance);
            Assert.Empty(await verify.WalletTransactions.ToListAsync());
        }

        [Fact]
        public async Task PayOSWebhook_SqliteTransaction_CreditsOnceOnReplay()
        {
            var (_, memberId) = await SeedAsync();
            var gateway = new StubGateway();

            long orderCode;
            using (var ctx = CreateContext())
            {
                var paymentService = NewPaymentService(ctx, gateway);
                var pkg = await ctx.CreditPackages.SingleAsync();
                var link = await paymentService.CreateTopUpPaymentAsync(memberId, new TopUpRequest
                {
                    PackageId = pkg.PackageId,
                    FrontendOrigin = "http://localhost:5173"
                });
                Assert.True(link.Success, link.Message);
                orderCode = link.Data!.ProviderOrderCode;
            }

            gateway.Result = new WebhookVerificationResult
            {
                IsValid = true,
                OrderCode = orderCode,
                Amount = 50000m,
                Code = "00",
                Reference = "SQLITE-REF-1"
            };

            using (var ctx = CreateContext())
            {
                var res = await NewPaymentService(ctx, gateway).ProcessPayOSWebhookAsync(new Webhook());
                Assert.True(res.Success, res.Message);
            }

            using (var ctx = CreateContext())
            {
                var replay = await NewPaymentService(ctx, gateway).ProcessPayOSWebhookAsync(new Webhook());
                Assert.True(replay.Success, replay.Message);
            }

            using var verify = CreateContext();
            Assert.Equal(300 + 5200, (await verify.Wallets.SingleAsync(w => w.UserId == memberId)).Balance);
            Assert.Equal(1, await verify.WalletTransactions.CountAsync());
        }

        private PaymentService NewPaymentService(SystemDbContext ctx, IPaymentGateway gateway)
        {
            var cfg = new ConfigurationBuilder()
                .AddInMemoryCollection(new Dictionary<string, string?> { ["PayOS:FrontendOrigin"] = "http://localhost:5173" })
                .Build();
            return new PaymentService(
                ctx,
                new WalletRepository(ctx),
                new CreditPackageRepository(ctx),
                new PaymentRepository(ctx),
                gateway,
                cfg,
                NullLogger<PaymentService>.Instance);
        }

        private sealed class FailOnWalletTransactionSaveInterceptor : SaveChangesInterceptor
        {
            public override InterceptionResult<int> SavingChanges(DbContextEventData eventData, InterceptionResult<int> result)
            {
                if (eventData.Context != null && eventData.Context.ChangeTracker.Entries<WalletTransaction>().Any(e => e.State == EntityState.Added))
                {
                    throw new InvalidOperationException("Simulated DB failure when writing WalletTransaction");
                }
                return base.SavingChanges(eventData, result);
            }

            public override ValueTask<InterceptionResult<int>> SavingChangesAsync(
                DbContextEventData eventData,
                InterceptionResult<int> result,
                CancellationToken cancellationToken = default)
            {
                if (eventData.Context != null && eventData.Context.ChangeTracker.Entries<WalletTransaction>().Any(e => e.State == EntityState.Added))
                {
                    throw new InvalidOperationException("Simulated DB failure when writing WalletTransaction");
                }
                return base.SavingChangesAsync(eventData, result, cancellationToken);
            }
        }

        private sealed class StubGateway : IPaymentGateway
        {
            public string ProviderName => "PayOS";
            public WebhookVerificationResult Result { get; set; } = new() { IsValid = false };

            public Task<PaymentGatewayResult> CreatePaymentLinkAsync(PaymentLinkArgs args, CancellationToken cancellationToken = default) =>
                Task.FromResult(new PaymentGatewayResult { Success = true, CheckoutUrl = "https://pay.local", QrCode = "QR" });

            public Task<WebhookVerificationResult> VerifyWebhookAsync(Webhook webhook, CancellationToken cancellationToken = default) =>
                Task.FromResult(Result);
        }
    }
}
