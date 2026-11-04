using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Data.Sqlite;
using Microsoft.EntityFrameworkCore;
using SystemService.BLL.Common.Responses;
using SystemService.BLL.DTOs.Debate;
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

namespace SystemService.IntegrationTests
{
    public class CompetitionDebateIntegrationTests : IDisposable
    {
        private readonly SqliteConnection _connection;
        private readonly DbContextOptions<SystemDbContext> _options;

        public CompetitionDebateIntegrationTests()
        {
            _connection = new SqliteConnection("DataSource=:memory:");
            _connection.Open();

            _options = new DbContextOptionsBuilder<SystemDbContext>()
                .UseSqlite(_connection)
                .Options;

            using var context = CreateContext();
            context.Database.EnsureCreated();
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

        private async Task<(int organizerId, int judgeId, int player1Id, int player2Id, int topicId, int format1v1Id, int format2v2Id)> SeedTestDataAsync(SystemDbContext context)
        {
            var organizer = new User { FullName = "Organizer", Email = "org@test.com", PasswordHash = "hash" };
            var judge = new User { FullName = "Judge", Email = "judge@test.com", PasswordHash = "hash" };
            var p1 = new User { FullName = "Player 1", Email = "p1@test.com", PasswordHash = "hash" };
            var p2 = new User { FullName = "Player 2", Email = "p2@test.com", PasswordHash = "hash" };

            context.Users.AddRange(organizer, judge, p1, p2);

            var topic = new Topic
            {
                Title = "Should AI replace judges?",
                Description = "Debate on AI in judicial systems",
                Difficulty = "Medium",
                IsActive = true
            };
            context.Topics.Add(topic);

            var format1v1 = new DebateFormat
            {
                FormatName = "1 vs 1",
                MaxParticipants = 2,
                TotalRounds = 3,
                RoundDurationSeconds = 180,
                IsActive = true
            };
            var format2v2 = new DebateFormat
            {
                FormatName = "2 vs 2",
                MaxParticipants = 4,
                TotalRounds = 3,
                RoundDurationSeconds = 180,
                IsActive = true
            };
            context.DebateFormats.AddRange(format1v1, format2v2);

            await context.SaveChangesAsync();

            return (organizer.UserId, judge.UserId, p1.UserId, p2.UserId, topic.TopicId, format1v1.FormatId, format2v2.FormatId);
        }

        [Fact]
        public async Task Test1_Prepare1v1Match_SuccessAndParticipantMapping()
        {
            using var context = CreateContext();
            var (orgId, judgeId, p1Id, p2Id, topicId, f1v1, _) = await SeedTestDataAsync(context);

            var competition = new Competition
            {
                Title = "Championship 2026",
                CompetitionType = "INDIVIDUAL",
                CreatedBy = orgId,
                FormatId = f1v1,
                RegistrationStart = DateTime.UtcNow.AddDays(-5),
                RegistrationEnd = DateTime.UtcNow.AddDays(-1),
                StartDate = DateTime.UtcNow
            };
            context.Competitions.Add(competition);

            var round = new CompetitionRound
            {
                Competition = competition,
                RoundNumber = 1,
                RoundName = "Round 1"
            };
            context.CompetitionRounds.Add(round);

            var match = new CompetitionMatch
            {
                Competition = competition,
                Round = round,
                MatchNumber = 1,
                BracketPosition = 1,
                Status = "Ready",
                AssignedJudgeUserId = judgeId
            };
            context.CompetitionMatches.Add(match);

            var partPro = new MatchParticipant { Match = match, UserId = p1Id, Side = "PRO" };
            var partCon = new MatchParticipant { Match = match, UserId = p2Id, Side = "CON" };
            context.MatchParticipants.AddRange(partPro, partCon);
            await context.SaveChangesAsync();

            var debateRepo = new DebateRepository(context);
            var teamRepo = new CompetitionTeamRepository(context);
            var bridge = new CompetitionDebateBridgeService(context, debateRepo, teamRepo);

            // Act
            var result = await bridge.PrepareMatchDebateAsync(orgId, match.CompetitionMatchId, topicId);

            // Assert
            Assert.True(result.Success);
            Assert.NotNull(result.Data);
            Assert.Equal(DebateType.Competition, result.Data.DebateType);
            Assert.Equal(SessionStatus.Waiting, result.Data.Status);
            Assert.Equal(2, result.Data.Participants.Count);

            var pPro = result.Data.Participants.First(p => p.UserId == p1Id);
            var pCon = result.Data.Participants.First(p => p.UserId == p2Id);
            Assert.Equal(DebateSide.PRO, pPro.Side);
            Assert.Equal(DebateSide.CON, pCon.Side);

            // Verify match linkage
            var updatedMatch = await context.CompetitionMatches.FindAsync(match.CompetitionMatchId);
            Assert.NotNull(updatedMatch!.DebateSessionId);
            Assert.Equal(result.Data.SessionId, updatedMatch.DebateSessionId);

            // Verify 3 rounds created
            var sessionRounds = await context.DebateRounds.Where(r => r.DebateSessionId == result.Data.SessionId).ToListAsync();
            Assert.Equal(3, sessionRounds.Count);
        }

        [Fact]
        public async Task Test2_Prepare2v2Match_CaptainAndMemberMapping()
        {
            using var context = CreateContext();
            var (orgId, judgeId, p1Id, p2Id, topicId, _, f2v2) = await SeedTestDataAsync(context);

            var p3 = new User { FullName = "Player 3", Email = "p3@test.com", PasswordHash = "h" };
            var p4 = new User { FullName = "Player 4", Email = "p4@test.com", PasswordHash = "h" };
            context.Users.AddRange(p3, p4);
            await context.SaveChangesAsync();

            var competition = new Competition
            {
                Title = "Team Championship 2026",
                CompetitionType = "TEAM",
                CreatedBy = orgId,
                FormatId = f2v2,
                RegistrationStart = DateTime.UtcNow.AddDays(-5),
                RegistrationEnd = DateTime.UtcNow.AddDays(-1),
                StartDate = DateTime.UtcNow
            };
            context.Competitions.Add(competition);

            // Team A: Captain p1, Member p3
            var teamA = new CompetitionTeam { Competition = competition, TeamName = "Team Alpha", CaptainUserId = p1Id };
            teamA.TeamMembers.Add(new CompetitionTeamMember { Team = teamA, UserId = p3.UserId });

            // Team B: Captain p2, Member p4
            var teamB = new CompetitionTeam { Competition = competition, TeamName = "Team Beta", CaptainUserId = p2Id };
            teamB.TeamMembers.Add(new CompetitionTeamMember { Team = teamB, UserId = p4.UserId });

            context.CompetitionTeams.AddRange(teamA, teamB);

            var round = new CompetitionRound { Competition = competition, RoundNumber = 1, RoundName = "Finals" };
            context.CompetitionRounds.Add(round);

            var match = new CompetitionMatch
            {
                Competition = competition,
                Round = round,
                MatchNumber = 1,
                Status = "Ready",
                AssignedJudgeUserId = judgeId
            };
            context.CompetitionMatches.Add(match);

            var partPro = new MatchParticipant { Match = match, Team = teamA, Side = "PRO" };
            var partCon = new MatchParticipant { Match = match, Team = teamB, Side = "CON" };
            context.MatchParticipants.AddRange(partPro, partCon);
            await context.SaveChangesAsync();

            var debateRepo = new DebateRepository(context);
            var teamRepo = new CompetitionTeamRepository(context);
            var bridge = new CompetitionDebateBridgeService(context, debateRepo, teamRepo);

            // Act
            var result = await bridge.PrepareMatchDebateAsync(judgeId, match.CompetitionMatchId, topicId);

            // Assert
            Assert.True(result.Success);
            Assert.Equal(4, result.Data!.Participants.Count);

            var proParticipants = result.Data.Participants.Where(p => p.Side == DebateSide.PRO).Select(p => p.UserId!.Value).ToList();
            var conParticipants = result.Data.Participants.Where(p => p.Side == DebateSide.CON).Select(p => p.UserId!.Value).ToList();

            Assert.Contains(p1Id, proParticipants);
            Assert.Contains(p3.UserId, proParticipants);
            Assert.Contains(p2Id, conParticipants);
            Assert.Contains(p4.UserId, conParticipants);
        }

        [Fact]
        public async Task Test3_Prepare_RepeatedCallIsIdempotent()
        {
            using var context = CreateContext();
            var (orgId, judgeId, p1Id, p2Id, topicId, f1v1, _) = await SeedTestDataAsync(context);

            var competition = new Competition { Title = "C1", CompetitionType = "INDIVIDUAL", CreatedBy = orgId, FormatId = f1v1, RegistrationStart = DateTime.UtcNow.AddDays(-2), RegistrationEnd = DateTime.UtcNow, StartDate = DateTime.UtcNow };
            context.Competitions.Add(competition);
            var round = new CompetitionRound { Competition = competition, RoundNumber = 1, RoundName = "R1" };
            context.CompetitionRounds.Add(round);
            var match = new CompetitionMatch { Competition = competition, Round = round, MatchNumber = 1, Status = "Ready", AssignedJudgeUserId = judgeId };
            context.CompetitionMatches.Add(match);
            context.MatchParticipants.AddRange(new MatchParticipant { Match = match, UserId = p1Id, Side = "PRO" }, new MatchParticipant { Match = match, UserId = p2Id, Side = "CON" });
            await context.SaveChangesAsync();

            var bridge = new CompetitionDebateBridgeService(context, new DebateRepository(context), new CompetitionTeamRepository(context));

            var call1 = await bridge.PrepareMatchDebateAsync(orgId, match.CompetitionMatchId, topicId);
            var call2 = await bridge.PrepareMatchDebateAsync(orgId, match.CompetitionMatchId, topicId);

            Assert.True(call1.Success);
            Assert.True(call2.Success);
            Assert.Equal(call1.Data!.SessionId, call2.Data!.SessionId);

            // Exactly 1 debate session in database
            var totalSessions = await context.DebateSessions.CountAsync();
            Assert.Equal(1, totalSessions);
        }

        [Fact]
        public async Task Test4_Prepare_SimultaneousRequests_NoDuplicatesOrOrphans()
        {
            using var context = CreateContext();
            var (orgId, judgeId, p1Id, p2Id, topicId, f1v1, _) = await SeedTestDataAsync(context);

            var competition = new Competition { Title = "C1", CompetitionType = "INDIVIDUAL", CreatedBy = orgId, FormatId = f1v1, RegistrationStart = DateTime.UtcNow.AddDays(-2), RegistrationEnd = DateTime.UtcNow, StartDate = DateTime.UtcNow };
            context.Competitions.Add(competition);
            var round = new CompetitionRound { Competition = competition, RoundNumber = 1, RoundName = "R1" };
            context.CompetitionRounds.Add(round);
            var match = new CompetitionMatch { Competition = competition, Round = round, MatchNumber = 1, Status = "Ready", AssignedJudgeUserId = judgeId };
            context.CompetitionMatches.Add(match);
            context.MatchParticipants.AddRange(new MatchParticipant { Match = match, UserId = p1Id, Side = "PRO" }, new MatchParticipant { Match = match, UserId = p2Id, Side = "CON" });
            await context.SaveChangesAsync();

            // Run 5 simultaneous prepare calls using isolated contexts sharing the same in-memory connection
            var tasks = Enumerable.Range(0, 5).Select(async _ =>
            {
                using var threadContext = CreateContext();
                var threadBridge = new CompetitionDebateBridgeService(threadContext, new DebateRepository(threadContext), new CompetitionTeamRepository(threadContext));
                return await threadBridge.PrepareMatchDebateAsync(orgId, match.CompetitionMatchId, topicId);
            });

            var results = await Task.WhenAll(tasks);

            // All should succeed or return valid response
            foreach (var r in results)
            {
                Assert.True(r.Success);
            }

            // Exactly 1 session created, all referencing the same session ID
            var firstSessionId = results[0].Data!.SessionId;
            foreach (var r in results)
            {
                Assert.Equal(firstSessionId, r.Data!.SessionId);
            }

            using var verifyContext = CreateContext();
            var sessionCount = await verifyContext.DebateSessions.CountAsync();
            Assert.Equal(1, sessionCount);
        }

        [Fact]
        public async Task Test5_Prepare_InvalidTopicId_FailsWithoutFallback()
        {
            using var context = CreateContext();
            var (orgId, judgeId, p1Id, p2Id, _, f1v1, _) = await SeedTestDataAsync(context);

            var competition = new Competition { Title = "C1", CompetitionType = "INDIVIDUAL", CreatedBy = orgId, FormatId = f1v1, RegistrationStart = DateTime.UtcNow.AddDays(-2), RegistrationEnd = DateTime.UtcNow, StartDate = DateTime.UtcNow };
            context.Competitions.Add(competition);
            var round = new CompetitionRound { Competition = competition, RoundNumber = 1, RoundName = "R1" };
            context.CompetitionRounds.Add(round);
            var match = new CompetitionMatch { Competition = competition, Round = round, MatchNumber = 1, Status = "Ready" };
            context.CompetitionMatches.Add(match);
            context.MatchParticipants.AddRange(new MatchParticipant { Match = match, UserId = p1Id, Side = "PRO" }, new MatchParticipant { Match = match, UserId = p2Id, Side = "CON" });
            await context.SaveChangesAsync();

            var bridge = new CompetitionDebateBridgeService(context, new DebateRepository(context), new CompetitionTeamRepository(context));

            var result = await bridge.PrepareMatchDebateAsync(orgId, match.CompetitionMatchId, 99999);

            Assert.False(result.Success);
            Assert.Contains("Chủ đề tranh biện không hợp lệ", result.Message);
            Assert.Equal(0, await context.DebateSessions.CountAsync());
        }

        [Fact]
        public async Task Test6_Start_OrganizerAndJudgeCanStart()
        {
            using var context = CreateContext();
            var (orgId, judgeId, p1Id, p2Id, topicId, f1v1, _) = await SeedTestDataAsync(context);

            var competition = new Competition { Title = "C1", CompetitionType = "INDIVIDUAL", CreatedBy = orgId, FormatId = f1v1, RegistrationStart = DateTime.UtcNow.AddDays(-2), RegistrationEnd = DateTime.UtcNow, StartDate = DateTime.UtcNow };
            context.Competitions.Add(competition);
            var round = new CompetitionRound { Competition = competition, RoundNumber = 1, RoundName = "R1" };
            context.CompetitionRounds.Add(round);
            var match = new CompetitionMatch { Competition = competition, Round = round, MatchNumber = 1, Status = "Ready", AssignedJudgeUserId = judgeId };
            context.CompetitionMatches.Add(match);
            context.MatchParticipants.AddRange(new MatchParticipant { Match = match, UserId = p1Id, Side = "PRO" }, new MatchParticipant { Match = match, UserId = p2Id, Side = "CON" });
            await context.SaveChangesAsync();

            var bridge = new CompetitionDebateBridgeService(context, new DebateRepository(context), new CompetitionTeamRepository(context));
            var prepareRes = await bridge.PrepareMatchDebateAsync(orgId, match.CompetitionMatchId, topicId);
            int sessionId = prepareRes.Data!.SessionId;

            var debateService = new DebateService(new DebateRepository(context), new UserRepository(context));

            // Act: Judge starts
            var startRes = await debateService.StartDebateSessionAsync(judgeId, sessionId);

            // Assert
            Assert.True(startRes.Success);
            Assert.Equal(SessionStatus.InProgress, startRes.Data!.Status);

            var updatedMatch = await context.CompetitionMatches.FindAsync(match.CompetitionMatchId);
            Assert.Equal("Ongoing", updatedMatch!.Status);
            Assert.NotNull(updatedMatch.StartedAt);
        }

        [Fact]
        public async Task Test7_Start_UnauthorizedUsersRejected()
        {
            using var context = CreateContext();
            var (orgId, judgeId, p1Id, p2Id, topicId, f1v1, _) = await SeedTestDataAsync(context);

            var competition = new Competition { Title = "C1", CompetitionType = "INDIVIDUAL", CreatedBy = orgId, FormatId = f1v1, RegistrationStart = DateTime.UtcNow.AddDays(-2), RegistrationEnd = DateTime.UtcNow, StartDate = DateTime.UtcNow };
            context.Competitions.Add(competition);
            var round = new CompetitionRound { Competition = competition, RoundNumber = 1, RoundName = "R1" };
            context.CompetitionRounds.Add(round);
            var match = new CompetitionMatch { Competition = competition, Round = round, MatchNumber = 1, Status = "Ready", AssignedJudgeUserId = judgeId };
            context.CompetitionMatches.Add(match);
            context.MatchParticipants.AddRange(new MatchParticipant { Match = match, UserId = p1Id, Side = "PRO" }, new MatchParticipant { Match = match, UserId = p2Id, Side = "CON" });
            await context.SaveChangesAsync();

            var bridge = new CompetitionDebateBridgeService(context, new DebateRepository(context), new CompetitionTeamRepository(context));
            var prepareRes = await bridge.PrepareMatchDebateAsync(orgId, match.CompetitionMatchId, topicId);
            int sessionId = prepareRes.Data!.SessionId;

            var debateService = new DebateService(new DebateRepository(context), new UserRepository(context));

            // Competitor p1 tries to start
            var startResPlayer = await debateService.StartDebateSessionAsync(p1Id, sessionId);
            Assert.False(startResPlayer.Success);
            Assert.Contains("Chỉ Ban tổ chức hoặc Trọng tài", startResPlayer.Message);

            // Random user tries to start
            var randomUser = new User { FullName = "Random", Email = "rnd@test.com", PasswordHash = "h" };
            context.Users.Add(randomUser);
            await context.SaveChangesAsync();

            var startResRnd = await debateService.StartDebateSessionAsync(randomUser.UserId, sessionId);
            Assert.False(startResRnd.Success);
            Assert.Contains("Chỉ Ban tổ chức hoặc Trọng tài", startResRnd.Message);
        }

        [Fact]
        public async Task Test8_SecurityGuards_PublicJoinAndSwapBlockedOnCompetitionSession()
        {
            using var context = CreateContext();
            var (orgId, judgeId, p1Id, p2Id, topicId, f1v1, _) = await SeedTestDataAsync(context);

            var competition = new Competition { Title = "C1", CompetitionType = "INDIVIDUAL", CreatedBy = orgId, FormatId = f1v1, RegistrationStart = DateTime.UtcNow.AddDays(-2), RegistrationEnd = DateTime.UtcNow, StartDate = DateTime.UtcNow };
            context.Competitions.Add(competition);
            var round = new CompetitionRound { Competition = competition, RoundNumber = 1, RoundName = "R1" };
            context.CompetitionRounds.Add(round);
            var match = new CompetitionMatch { Competition = competition, Round = round, MatchNumber = 1, Status = "Ready", AssignedJudgeUserId = judgeId };
            context.CompetitionMatches.Add(match);
            context.MatchParticipants.AddRange(new MatchParticipant { Match = match, UserId = p1Id, Side = "PRO" }, new MatchParticipant { Match = match, UserId = p2Id, Side = "CON" });
            await context.SaveChangesAsync();

            var bridge = new CompetitionDebateBridgeService(context, new DebateRepository(context), new CompetitionTeamRepository(context));
            var prepareRes = await bridge.PrepareMatchDebateAsync(orgId, match.CompetitionMatchId, topicId);
            int sessionId = prepareRes.Data!.SessionId;

            var intruder = new User { FullName = "Intruder", Email = "intruder@test.com", PasswordHash = "h" };
            context.Users.Add(intruder);
            await context.SaveChangesAsync();

            var debateService = new DebateService(new DebateRepository(context), new UserRepository(context));

            // 1. Join attempt blocked
            var joinRes = await debateService.JoinP2pSessionAsync(intruder.UserId, sessionId, new JoinSessionRequest());
            Assert.False(joinRes.Success);
            Assert.Contains("thuộc giải đấu", joinRes.Message);

            // 2. Switch side attempt blocked
            var switchRes = await debateService.SwitchSideAsync(p1Id, sessionId);
            Assert.False(switchRes.Success);
            Assert.Contains("Không thể đổi phe trong phiên tranh biện thuộc giải đấu", switchRes.Message);

            // 3. Swap request blocked
            var swapRes = await debateService.SendSwapSideRequestAsync(p1Id, sessionId, new SendSwapSideRequest { TargetUserId = p2Id });
            Assert.False(swapRes.Success);
            Assert.Contains("Không thể đổi phe trong phiên tranh biện thuộc giải đấu", swapRes.Message);
        }

        [Fact]
        public async Task Test9_StandaloneDebate_RegressionPreserved()
        {
            using var context = CreateContext();
            var (u1, u2, _, _, topicId, f1v1, _) = await SeedTestDataAsync(context);

            var debateService = new DebateService(new DebateRepository(context), new UserRepository(context));

            // Create standalone P2P session
            var createRes = await debateService.CreateP2pSessionAsync(u1, new CreateP2pSessionRequest
            {
                Title = "Casual debate",
                Topic = "Casual topic",
                UserSide = DebateSide.PRO,
                TurnTimeLimitSeconds = 180,
                IsAI = false
            });
            Assert.True(createRes.Success);
            int casualSessionId = createRes.Data!.SessionId;

            // u2 can join casual session
            var joinRes = await debateService.JoinP2pSessionAsync(u2, casualSessionId, new JoinSessionRequest());
            Assert.True(joinRes.Success);

            // Non-creator u2 cannot start
            var startU2 = await debateService.StartDebateSessionAsync(u2, casualSessionId);
            Assert.False(startU2.Success);
            Assert.Contains("Chỉ chủ phòng", startU2.Message);

            // Creator u1 can start
            var startU1 = await debateService.StartDebateSessionAsync(u1, casualSessionId);
            Assert.True(startU1.Success);
            Assert.Equal(SessionStatus.InProgress, startU1.Data!.Status);
        }

        [Fact]
        public async Task StandaloneStart_ConcurrentRequests_OnlyOneWins()
        {
            var dbPath = System.IO.Path.Combine(System.IO.Path.GetTempPath(), $"standalone_start_{Guid.NewGuid():N}.db");
            var opts = new DbContextOptionsBuilder<SystemDbContext>()
                .UseSqlite($"Data Source={dbPath}")
                .Options;

            try
            {
                int creatorId;
                int sessionId;
                using (var setup = new TestSystemDbContext(opts))
                {
                    setup.Database.EnsureCreated();
                    var (orgId, _, p1Id, p2Id, topicId, formatId, _) = await SeedTestDataAsync(setup);
                    creatorId = orgId;

                    var session = new DebateSession
                    {
                        TopicId = topicId,
                        FormatId = formatId,
                        CreatedBy = creatorId,
                        Status = SessionStatus.Waiting,
                        CreatedAt = DateTime.UtcNow
                    };
                    session.Participants.Add(new DebateParticipant
                    {
                        UserId = p1Id, ParticipantType = ParticipantType.USER,
                        Side = DebateSide.PRO, JoinedAt = DateTime.UtcNow
                    });
                    session.Participants.Add(new DebateParticipant
                    {
                        UserId = p2Id, ParticipantType = ParticipantType.USER,
                        Side = DebateSide.CON, JoinedAt = DateTime.UtcNow
                    });
                    session.DebateRounds.Add(new DebateRound
                    {
                        RoundNumber = 1, RoundType = RoundType.OPENING, CreatedAt = DateTime.UtcNow
                    });
                    session.DebateRounds.Add(new DebateRound
                    {
                        RoundNumber = 2, RoundType = RoundType.REBUTTAL, CreatedAt = DateTime.UtcNow
                    });
                    session.DebateRounds.Add(new DebateRound
                    {
                        RoundNumber = 3, RoundType = RoundType.CLOSING, CreatedAt = DateTime.UtcNow
                    });
                    setup.DebateSessions.Add(session);
                    await setup.SaveChangesAsync();
                    sessionId = session.DebateSessionId;
                }

                using var gate = new ManualResetEventSlim(false);
                var startTasks = Enumerable.Range(0, 2).Select(_ => Task.Run(async () =>
                {
                    using var context = new TestSystemDbContext(opts);
                    var service = new DebateService(new DebateRepository(context), new UserRepository(context));
                    gate.Wait();
                    return await service.StartDebateSessionAsync(creatorId, sessionId);
                })).ToArray();

                gate.Set();
                var results = await Task.WhenAll(startTasks);
                Assert.Single(results, result => result.Success);
                Assert.Single(results, result => !result.Success);

                using var verify = new TestSystemDbContext(opts);
                var finalSession = await verify.DebateSessions
                    .Include(s => s.DebateRounds)
                    .SingleAsync(s => s.DebateSessionId == sessionId);
                Assert.Equal(SessionStatus.InProgress, finalSession.Status);
                Assert.NotNull(finalSession.DebateRounds.Single(r => r.RoundNumber == 1).StartTime);
            }
            finally
            {
                if (System.IO.File.Exists(dbPath))
                {
                    try { System.IO.File.Delete(dbPath); } catch { }
                }
            }
        }

        [Fact]
        public async Task CompetitionCompletion_UpdatesMatchToEvaluatingInSameFlow()
        {
            using var context = CreateContext();
            var (orgId, judgeId, p1Id, p2Id, topicId, f1v1, _) = await SeedTestDataAsync(context);

            var competition = new Competition
            {
                Title = "Completion sync", CompetitionType = "INDIVIDUAL", CreatedBy = orgId,
                FormatId = f1v1, RegistrationStart = DateTime.UtcNow.AddDays(-2),
                RegistrationEnd = DateTime.UtcNow, StartDate = DateTime.UtcNow
            };
            var round = new CompetitionRound { Competition = competition, RoundNumber = 1, RoundName = "R1" };
            var match = new CompetitionMatch
            {
                Competition = competition, Round = round, MatchNumber = 1,
                Status = "Ready", AssignedJudgeUserId = judgeId
            };
            context.CompetitionMatches.Add(match);
            context.MatchParticipants.AddRange(
                new MatchParticipant { Match = match, UserId = p1Id, Side = "PRO" },
                new MatchParticipant { Match = match, UserId = p2Id, Side = "CON" });
            await context.SaveChangesAsync();

            var bridge = new CompetitionDebateBridgeService(context, new DebateRepository(context), new CompetitionTeamRepository(context));
            var prepare = await bridge.PrepareMatchDebateAsync(orgId, match.CompetitionMatchId, topicId);
            Assert.True(prepare.Success);
            var debateService = new DebateService(new DebateRepository(context), new UserRepository(context));
            var start = await debateService.StartDebateSessionAsync(orgId, prepare.Data!.SessionId);
            Assert.True(start.Success);

            var session = await context.DebateSessions
                .Include(s => s.Participants)
                .Include(s => s.DebateRounds)
                .SingleAsync(s => s.DebateSessionId == prepare.Data.SessionId);
            var pro = session.Participants.Single(p => p.UserId == p1Id);
            var con = session.Participants.Single(p => p.UserId == p2Id);
            var rounds = session.DebateRounds.OrderBy(r => r.RoundNumber).ToArray();

            foreach (var debateRound in rounds.Take(2))
            {
                context.Arguments.AddRange(
                    new Argument { RoundId = debateRound.RoundId, ParticipantId = pro.ParticipantId, Content = "Pro", SubmittedAt = DateTime.UtcNow },
                    new Argument { RoundId = debateRound.RoundId, ParticipantId = con.ParticipantId, Content = "Con", SubmittedAt = DateTime.UtcNow });
            }
            context.Arguments.Add(new Argument
            {
                RoundId = rounds[2].RoundId, ParticipantId = pro.ParticipantId,
                Content = "Final pro", SubmittedAt = DateTime.UtcNow
            });
            await context.SaveChangesAsync();

            var result = await debateService.SubmitArgumentAsync(p2Id, session.DebateSessionId,
                new SubmitArgumentRequest { Content = "Final con" });

            Assert.True(result.Success, result.Message);
            var completedSession = await context.DebateSessions.FindAsync(session.DebateSessionId);
            var updatedMatch = await context.CompetitionMatches.FindAsync(match.CompetitionMatchId);
            Assert.Equal(SessionStatus.Completed, completedSession!.Status);
            Assert.NotNull(completedSession.EndTime);
            Assert.Equal("Evaluating", updatedMatch!.Status);
            Assert.NotNull(updatedMatch.UpdatedAt);
            Assert.Null(updatedMatch.CompletedAt);
        }

        [Fact]
        public async Task Test10_ConcurrentStart_ExactlyOnceTransition()
        {
            var dbPath = System.IO.Path.Combine(System.IO.Path.GetTempPath(), $"concurrent_test_{Guid.NewGuid():N}.db");
            var connStr = $"Data Source={dbPath}";
            var opts = new DbContextOptionsBuilder<SystemDbContext>()
                .UseSqlite(connStr)
                .Options;

            try
            {
                using (var setupContext = new TestSystemDbContext(opts))
                {
                    setupContext.Database.EnsureCreated();
                    var (orgId, judgeId, p1Id, p2Id, topicId, f1v1, _) = await SeedTestDataAsync(setupContext);

                    var competition = new Competition { Title = "C1", CompetitionType = "INDIVIDUAL", CreatedBy = orgId, FormatId = f1v1, RegistrationStart = DateTime.UtcNow.AddDays(-2), RegistrationEnd = DateTime.UtcNow, StartDate = DateTime.UtcNow };
                    setupContext.Competitions.Add(competition);
                    var round = new CompetitionRound { Competition = competition, RoundNumber = 1, RoundName = "R1" };
                    setupContext.CompetitionRounds.Add(round);
                    var match = new CompetitionMatch { Competition = competition, Round = round, MatchNumber = 1, Status = "Ready", AssignedJudgeUserId = judgeId };
                    setupContext.CompetitionMatches.Add(match);
                    setupContext.MatchParticipants.AddRange(new MatchParticipant { Match = match, UserId = p1Id, Side = "PRO" }, new MatchParticipant { Match = match, UserId = p2Id, Side = "CON" });
                    await setupContext.SaveChangesAsync();

                    var bridge = new CompetitionDebateBridgeService(setupContext, new DebateRepository(setupContext), new CompetitionTeamRepository(setupContext));
                    var prepareRes = await bridge.PrepareMatchDebateAsync(orgId, match.CompetitionMatchId, topicId);
                    int sessionId = prepareRes.Data!.SessionId;

                    // Two simultaneous start requests from Organizer and Judge across separate contexts/connections
                    using var startGate = new ManualResetEventSlim(false);
                    var task1 = Task.Run(async () =>
                    {
                        using var c1 = new TestSystemDbContext(opts);
                        var s1 = new DebateService(new DebateRepository(c1), new UserRepository(c1));
                        startGate.Wait();
                        return await s1.StartDebateSessionAsync(orgId, sessionId);
                    });

                    var task2 = Task.Run(async () =>
                    {
                        using var c2 = new TestSystemDbContext(opts);
                        var s2 = new DebateService(new DebateRepository(c2), new UserRepository(c2));
                        startGate.Wait();
                        return await s2.StartDebateSessionAsync(judgeId, sessionId);
                    });

                    startGate.Set();
                    var results = await Task.WhenAll(task1, task2);

                    int successCount = results.Count(r => r.Success);
                    int failureCount = results.Count(r => !r.Success);

                    Assert.Equal(1, successCount);
                    Assert.Equal(1, failureCount);

                    using var verifyContext = new TestSystemDbContext(opts);
                    var finalSession = await verifyContext.DebateSessions.FindAsync(sessionId);
                    Assert.Equal(SessionStatus.InProgress, finalSession!.Status);

                    var finalMatch = await verifyContext.CompetitionMatches.FindAsync(match.CompetitionMatchId);
                    Assert.Equal("Ongoing", finalMatch!.Status);
                }
            }
            finally
            {
                if (System.IO.File.Exists(dbPath))
                {
                    try { System.IO.File.Delete(dbPath); } catch { }
                }
            }
        }

        [Fact]
        public async Task Test11_Prepare2v2_InvalidTeamRoster_Rejected()
        {
            using var context = CreateContext();
            var (orgId, judgeId, p1Id, p2Id, topicId, _, f2v2) = await SeedTestDataAsync(context);

            var competition = new Competition { Title = "C1", CompetitionType = "TEAM", CreatedBy = orgId, FormatId = f2v2, RegistrationStart = DateTime.UtcNow.AddDays(-2), RegistrationEnd = DateTime.UtcNow, StartDate = DateTime.UtcNow };
            context.Competitions.Add(competition);

            // Team A has ONLY Captain (1 member total -> invalid)
            var teamA = new CompetitionTeam { Competition = competition, TeamName = "Team A", CaptainUserId = p1Id };
            // Team B has Captain p2
            var teamB = new CompetitionTeam { Competition = competition, TeamName = "Team B", CaptainUserId = p2Id };
            context.CompetitionTeams.AddRange(teamA, teamB);

            var round = new CompetitionRound { Competition = competition, RoundNumber = 1, RoundName = "R1" };
            context.CompetitionRounds.Add(round);
            var match = new CompetitionMatch { Competition = competition, Round = round, MatchNumber = 1, Status = "Ready", AssignedJudgeUserId = judgeId };
            context.CompetitionMatches.Add(match);
            context.MatchParticipants.AddRange(new MatchParticipant { Match = match, Team = teamA, Side = "PRO" }, new MatchParticipant { Match = match, Team = teamB, Side = "CON" });
            await context.SaveChangesAsync();

            var bridge = new CompetitionDebateBridgeService(context, new DebateRepository(context), new CompetitionTeamRepository(context));

            var result = await bridge.PrepareMatchDebateAsync(orgId, match.CompetitionMatchId, topicId);

            Assert.False(result.Success);
            Assert.Contains("không đủ điều kiện thi đấu", result.Message);
            Assert.Equal(0, await context.DebateSessions.CountAsync());
        }

        [Fact]
        public async Task Test12_Start_OrganizerExplicitStart()
        {
            using var context = CreateContext();
            var (orgId, judgeId, p1Id, p2Id, topicId, f1v1, _) = await SeedTestDataAsync(context);

            var competition = new Competition { Title = "C1", CompetitionType = "INDIVIDUAL", CreatedBy = orgId, FormatId = f1v1, RegistrationStart = DateTime.UtcNow.AddDays(-2), RegistrationEnd = DateTime.UtcNow, StartDate = DateTime.UtcNow };
            context.Competitions.Add(competition);
            var round = new CompetitionRound { Competition = competition, RoundNumber = 1, RoundName = "R1" };
            context.CompetitionRounds.Add(round);
            var match = new CompetitionMatch { Competition = competition, Round = round, MatchNumber = 1, Status = "Ready", AssignedJudgeUserId = judgeId };
            context.CompetitionMatches.Add(match);
            context.MatchParticipants.AddRange(new MatchParticipant { Match = match, UserId = p1Id, Side = "PRO" }, new MatchParticipant { Match = match, UserId = p2Id, Side = "CON" });
            await context.SaveChangesAsync();

            var bridge = new CompetitionDebateBridgeService(context, new DebateRepository(context), new CompetitionTeamRepository(context));
            var prepareRes = await bridge.PrepareMatchDebateAsync(orgId, match.CompetitionMatchId, topicId);
            int sessionId = prepareRes.Data!.SessionId;

            var debateService = new DebateService(new DebateRepository(context), new UserRepository(context));

            // Act: Organizer starts
            var startRes = await debateService.StartDebateSessionAsync(orgId, sessionId);

            // Assert
            Assert.True(startRes.Success);
            Assert.Equal(SessionStatus.InProgress, startRes.Data!.Status);

            var updatedMatch = await context.CompetitionMatches.FindAsync(match.CompetitionMatchId);
            Assert.Equal("Ongoing", updatedMatch!.Status);
        }
    }
}
