using SystemService.BLL.DTOs.Identity.Users;
using SystemService.BLL.Services.Identity.Implementations;
using SystemService.DAL.Entities.Debate;
using SystemService.DAL.Entities.Debate.Enums;
using SystemService.DAL.Entities.Identity;
using SystemService.Tests.Debate;
using static SystemService.Tests.Debate.DebateTestHarness;

namespace SystemService.Tests.Identity
{
    /// <summary>GET api/learners/featured: Members ranked by the AI score of their side in completed debates.</summary>
    public class FeaturedLearnerServiceTests : IDisposable
    {
        private readonly DebateTestHarness _harness = new();
        private int _nextSession = 100;

        public void Dispose() => _harness.Dispose();

        [Fact]
        public async Task RanksByAverageScore_ThenWins_AndCountsTheLearnersOwnSide()
        {
            // A: PRO 8 (won), CON 6 (lost to 7) => avg 7, 1 win; B: CON 7 (won), PRO 7 (won vs 5) => avg 7, 2 wins
            Debate(UserA, DebateSide.PRO, pro: 8, con: 4);
            Debate(UserA, DebateSide.CON, pro: 7, con: 6);
            Debate(UserB, DebateSide.CON, pro: 3, con: 7);
            Debate(UserB, DebateSide.PRO, pro: 7, con: 5);

            var list = await GetAsync(new FeaturedLearnersQuery());

            Assert.Equal(new[] { UserB, UserA }, list.Select(l => l.UserId));
            var b = list[0];
            Assert.Equal((1, 2, 2, 7m, 7m, 1m), (b.Rank, b.DebatesCompleted, b.Wins, b.AverageScore, b.BestScore, b.WinRate));
            Assert.Equal((2, 8m, 1), (list[1].Rank, list[1].BestScore, list[1].Wins));
        }

        [Fact]
        public async Task LeavesOut_StaffInactiveAi_UnfinishedUnscoredOldDebates_AndTooFewDebates()
        {
            Debate(UserA, DebateSide.PRO, pro: 9, con: 1);
            Debate(UserA, DebateSide.PRO, pro: 9, con: 1);
            Debate(Outsider, DebateSide.PRO, pro: 10, con: 1); // only one debate (MinDebates 2)

            Debate(UserB, DebateSide.PRO, pro: 10, con: 1, status: SessionStatus.InProgress);
            Debate(UserB, DebateSide.PRO, pro: null, con: 1);
            Debate(UserB, DebateSide.PRO, pro: 10, con: 1, endedDaysAgo: 40);
            Debate(UserB, DebateSide.PRO, pro: 10, con: 1, judged: false);

            int admin = AddUser("Admin", role: "Admin");
            Debate(admin, DebateSide.PRO, pro: 10, con: 1);
            Debate(admin, DebateSide.PRO, pro: 10, con: 1);
            int inactive = AddUser("Inactive", active: false);
            Debate(inactive, DebateSide.PRO, pro: 10, con: 1);
            Debate(inactive, DebateSide.PRO, pro: 10, con: 1);

            var list = await GetAsync(new FeaturedLearnersQuery());
            Assert.Equal(new[] { UserA }, list.Select(l => l.UserId));

            // all time and one debate: B's old debate and the Outsider count now
            var all = await GetAsync(new FeaturedLearnersQuery { Days = 0, MinDebates = 1 });
            Assert.Equal(new[] { Outsider, UserB, UserA }, all.Select(l => l.UserId));
            Assert.Equal(1, all.Single(l => l.UserId == UserB).DebatesCompleted);
        }

        [Fact]
        public async Task UsesTheLatestJudgement_AndHonoursTheLimit()
        {
            int session = Debate(UserA, DebateSide.PRO, pro: 2, con: 9);
            Debate(UserA, DebateSide.PRO, pro: 5, con: 5);
            using (var context = _harness.CreateContext())
            {
                context.AIJudgements.Add(new AIJudgement
                {
                    DebateSessionId = session, OverallScorePro = 9, OverallScoreCon = 2, CreatedAt = DateTime.UtcNow.AddMinutes(5),
                });
                context.SaveChanges();
            }
            Debate(UserB, DebateSide.PRO, pro: 1, con: 2);
            Debate(UserB, DebateSide.PRO, pro: 1, con: 2);

            var list = await GetAsync(new FeaturedLearnersQuery { Limit = 1 });

            var a = Assert.Single(list);
            Assert.Equal((UserA, 7m, 1), (a.UserId, a.AverageScore, a.Wins));
            Assert.Equal("Learner A", a.FullName);
        }

        private async Task<List<FeaturedLearnerDto>> GetAsync(FeaturedLearnersQuery query)
        {
            using var context = _harness.CreateContext();
            var result = await new FeaturedLearnerService(context).GetFeaturedLearnersAsync(query);
            Assert.True(result.Success, result.Message);
            return result.Data!;
        }

        private int Debate(int userId, DebateSide side, decimal? pro, decimal? con,
            SessionStatus status = SessionStatus.Completed, int endedDaysAgo = 1, bool judged = true)
        {
            using var context = _harness.CreateContext();
            int id = _nextSession++;
            var ended = DateTime.UtcNow.AddDays(-endedDaysAgo);
            context.DebateSessions.Add(new DebateSession
            {
                DebateSessionId = id, TopicId = 1, FormatId = 1, CreatedBy = userId, Status = status,
                CreatedAt = ended.AddHours(-1), EndTime = status == SessionStatus.Completed ? ended : null,
            });
            context.DebateParticipants.AddRange(
                new DebateParticipant { DebateSessionId = id, UserId = userId, ParticipantType = ParticipantType.USER, Side = side },
                new DebateParticipant { DebateSessionId = id, ParticipantType = ParticipantType.AI, Side = side == DebateSide.PRO ? DebateSide.CON : DebateSide.PRO });
            if (judged)
            {
                context.AIJudgements.Add(new AIJudgement { DebateSessionId = id, OverallScorePro = pro, OverallScoreCon = con, CreatedAt = ended });
            }
            context.SaveChanges();
            return id;
        }

        private int AddUser(string name, string? role = null, bool active = true)
        {
            using var context = _harness.CreateContext();
            var user = new User { FullName = name, Email = $"{Guid.NewGuid():N}@test.local", IsActive = active };
            context.Users.Add(user);
            context.SaveChanges();
            if (role != null)
            {
                var r = context.Roles.FirstOrDefault(x => x.RoleName == role) ?? new Role { RoleName = role };
                context.UserRoles.Add(new UserRole { UserId = user.UserId, Role = r });
                context.SaveChanges();
            }
            return user.UserId;
        }
    }
}
