using SystemService.BLL.DTOs.Debate;
using SystemService.DAL.Entities.Debate.Enums;
using static SystemService.Tests.Debate.DebateTestHarness;

namespace SystemService.Tests.Debate
{
    public class DebateSessionIdentityTests : IDisposable
    {
        private readonly DebateTestHarness _harness = new();

        public void Dispose() => _harness.Dispose();

        // ---- DebateType is derived from the session ----

        [Fact]
        public async Task AiSession_ReportsAiPractice_InDetailsHistoryAndSubmitResponses()
        {
            int sessionId = await _harness.StartAiSessionAsync(DebateSide.PRO);

            var submitted = ApiResponseAssert.Succeeds(await _harness.UserSubmitsAsync(UserA, sessionId));

            Assert.Equal(DebateType.AiPractice, submitted.DebateType);
            Assert.Equal(DebateType.AiPractice, await DetailsTypeAsync(sessionId));
            Assert.Equal(DebateType.AiPractice, await HistoryTypeAsync(UserA, sessionId));
        }

        [Fact]
        public async Task P2pSession_ReportsP2pMatch_ForBothPlayers()
        {
            int sessionId = await _harness.StartP2pSessionAsync(DebateSide.PRO);

            Assert.Equal(DebateType.P2pMatch, await DetailsTypeAsync(sessionId));
            Assert.Equal(DebateType.P2pMatch, await HistoryTypeAsync(UserA, sessionId));
            Assert.Equal(DebateType.P2pMatch, await HistoryTypeAsync(UserB, sessionId));
        }

        [Fact]
        public async Task P2pSession_WaitingForOpponent_ReportsP2pMatch()
        {
            var created = ApiResponseAssert.Succeeds(await _harness.NewService().CreateP2pSessionAsync(UserA, new CreateP2pSessionRequest
            {
                Title = "Motion",
                Topic = "Topic",
                UserSide = DebateSide.PRO,
                IsAI = false
            }));

            Assert.Equal(DebateType.P2pMatch, created.DebateType);
        }

        [Theory]
        [InlineData(false)]
        [InlineData(true)] // 2v2 with AI opponents must not look like an AI practice, teammates are real players
        public async Task TwoVsTwoSession_ReportsP2pMatch(bool isAi)
        {
            var created = ApiResponseAssert.Succeeds(await _harness.NewService().Create2v2SessionAsync(UserA, new Create2v2SessionRequest
            {
                Title = "Motion",
                Topic = "Topic",
                UserSide = DebateSide.PRO,
                IsAI = isAi
            }));

            Assert.Equal(DebateType.P2pMatch, created.DebateType);
            Assert.Equal(DebateType.P2pMatch, await HistoryTypeAsync(UserA, created.SessionId));
        }

        // ---- UserId on transcript entries ----

        [Fact]
        public async Task AiSessionTranscript_HasUserIdForTheLearner_AndNullForTheAi()
        {
            int sessionId = await _harness.StartAiSessionAsync(DebateSide.PRO);
            ApiResponseAssert.Succeeds(await _harness.UserSubmitsAsync(UserA, sessionId));
            ApiResponseAssert.Succeeds(await _harness.AiSubmitsAsync(sessionId, 1));

            var transcript = ApiResponseAssert.Succeeds(await _harness.NewService().GetTranscriptAsync(UserA, sessionId));

            Assert.Equal(new int?[] { UserA, null }, transcript.Arguments.Select(a => a.UserId).ToArray());
            Assert.Equal(new[] { false, true }, transcript.Arguments.Select(a => a.IsAI).ToArray());
        }

        [Fact]
        public async Task P2pTranscript_IdentifiesEachPlayer()
        {
            int sessionId = await _harness.StartP2pSessionAsync(DebateSide.PRO);
            ApiResponseAssert.Succeeds(await _harness.UserSubmitsAsync(UserA, sessionId));
            ApiResponseAssert.Succeeds(await _harness.UserSubmitsAsync(UserB, sessionId));

            var transcript = ApiResponseAssert.Succeeds(await _harness.NewService().GetTranscriptAsync(UserB, sessionId));

            Assert.Equal(new int?[] { UserA, UserB }, transcript.Arguments.Select(a => a.UserId).ToArray());
        }

        [Fact]
        public async Task AiArgumentResponse_HasNullUserId()
        {
            int sessionId = await _harness.StartAiSessionAsync(DebateSide.CON);

            var result = ApiResponseAssert.Succeeds(await _harness.AiSubmitsAsync(sessionId, 0));

            Assert.Null(result.Argument.UserId);
            Assert.True(result.Argument.IsAI);
        }

        private async Task<DebateType> DetailsTypeAsync(int sessionId)
        {
            return ApiResponseAssert.Succeeds(await _harness.NewService().GetSessionDetailsAsync(UserA, sessionId)).DebateType;
        }

        private async Task<DebateType> HistoryTypeAsync(int userId, int sessionId)
        {
            var history = ApiResponseAssert.Succeeds(await _harness.NewService().GetUserHistoryAsync(userId));
            return history.Single(h => h.SessionId == sessionId).DebateType;
        }
    }
}
