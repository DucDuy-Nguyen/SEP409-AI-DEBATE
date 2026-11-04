using SystemService.BLL.DTOs.Debate;
using SystemService.BLL.Services.Identity.Implementations;
using SystemService.DAL.Entities.Debate.Enums;
using SystemService.DAL.Repositories.Debate.Implementations;
using SystemService.DAL.Repositories.Identity.Implementations;
using SystemService.Tests.Debate;
using static SystemService.Tests.Debate.DebateTestHarness;

namespace SystemService.Tests.Identity
{
    public class AdminDashboardStatsTests : IDisposable
    {
        private readonly DebateTestHarness _harness = new();

        public void Dispose() => _harness.Dispose();

        [Fact]
        public async Task TotalDebateSessions_CountsOnlyCompleted()
        {
            await _harness.StartAiSessionAsync(DebateSide.PRO); // InProgress

            ApiResponseAssert.Succeeds(await _harness.NewService().CreateP2pSessionAsync(UserA, new CreateP2pSessionRequest
            {
                Title = "Motion",
                Topic = "Topic",
                UserSide = DebateSide.PRO,
                IsAI = false
            })); // Waiting

            int cancelledId = await _harness.StartAiSessionAsync(DebateSide.PRO);
            ApiResponseAssert.Succeeds(await _harness.NewService().LeaveSessionAsync(UserA, cancelledId));

            int completedId = await _harness.StartAiSessionAsync(DebateSide.CON);
            ApiResponseAssert.Succeeds(await _harness.AiSubmitsAsync(completedId, 0));
            ApiResponseAssert.Succeeds(await _harness.UserSubmitsAsync(UserA, completedId));
            ApiResponseAssert.Succeeds(await _harness.AiSubmitsAsync(completedId, 2));
            ApiResponseAssert.Succeeds(await _harness.UserSubmitsAsync(UserA, completedId));
            ApiResponseAssert.Succeeds(await _harness.UserSubmitsAsync(UserA, completedId));
            ApiResponseAssert.Succeeds(await _harness.AiSubmitsAsync(completedId, 5));

            using var context = _harness.CreateContext();
            var service = new AdminService(new UserRepository(context), new RoleRepository(context), new DebateRepository(context), new TopicRepository(context));

            var stats = ApiResponseAssert.Succeeds(await service.GetDashboardStatsAsync());

            Assert.Equal(1, stats.TotalDebateSessions);
            Assert.Equal(3, stats.TotalUsers);
        }
    }
}
