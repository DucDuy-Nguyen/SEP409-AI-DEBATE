using SystemService.BLL.Common.Debate;
using SystemService.BLL.DTOs.Debate;
using SystemService.DAL.Entities.Debate.Enums;
using static SystemService.Tests.Debate.DebateTestHarness;

namespace SystemService.Tests.Debate
{
    public class SubmitAiArgumentTests : IDisposable
    {
        private readonly DebateTestHarness _harness = new();

        public void Dispose() => _harness.Dispose();

        [Fact]
        public async Task SameTurnTwice_StoresOneArgument_AndReturnsTheOriginal()
        {
            int sessionId = await _harness.StartAiSessionAsync(DebateSide.PRO);
            ApiResponseAssert.Succeeds(await _harness.UserSubmitsAsync(UserA, sessionId));

            var first = ApiResponseAssert.Succeeds(await _harness.AiSubmitsAsync(sessionId, 1, "original"));
            var retry = ApiResponseAssert.Succeeds(await _harness.AiSubmitsAsync(sessionId, 1, "retried text"));

            Assert.False(first.AlreadyRecorded);
            Assert.True(retry.AlreadyRecorded);
            Assert.Equal(first.Argument.ArgumentId, retry.Argument.ArgumentId);
            Assert.Equal("original", retry.Argument.Content);
            Assert.True(retry.Argument.IsAI);
            Assert.Equal(DebateSide.CON, retry.Argument.Side);
            Assert.Equal(2, _harness.ArgumentCount(sessionId));
        }

        [Fact]
        public async Task RetryOfFinalTurn_AfterSessionCompleted_ReturnsExisting()
        {
            int sessionId = await _harness.StartAiSessionAsync(DebateSide.CON);
            ApiResponseAssert.Succeeds(await _harness.AiSubmitsAsync(sessionId, 0));
            ApiResponseAssert.Succeeds(await _harness.UserSubmitsAsync(UserA, sessionId));
            ApiResponseAssert.Succeeds(await _harness.AiSubmitsAsync(sessionId, 2));
            ApiResponseAssert.Succeeds(await _harness.UserSubmitsAsync(UserA, sessionId));
            ApiResponseAssert.Succeeds(await _harness.UserSubmitsAsync(UserA, sessionId));
            ApiResponseAssert.Succeeds(await _harness.AiSubmitsAsync(sessionId, 5));

            var retry = ApiResponseAssert.Succeeds(await _harness.AiSubmitsAsync(sessionId, 5));

            Assert.True(retry.AlreadyRecorded);
            Assert.Equal(SessionStatus.Completed, retry.Session.Status);
            Assert.Equal(6, _harness.ArgumentCount(sessionId));
        }

        [Theory]
        [InlineData(0)] // opening PRO = user
        [InlineData(2)] // rebuttal PRO = user
        [InlineData(5)] // closing PRO = user
        public async Task TurnBelongingToUser_ReturnsNotAiTurn(int turnIndex)
        {
            int sessionId = await _harness.StartAiSessionAsync(DebateSide.PRO);

            ApiResponseAssert.FailsWith(await _harness.AiSubmitsAsync(sessionId, turnIndex), DebateErrorCodes.NotAiTurn);
            Assert.Equal(0, _harness.ArgumentCount(sessionId));
        }

        [Fact]
        public async Task AiTurnBeforeItIsNext_ReturnsTurnOutOfOrder()
        {
            int sessionId = await _harness.StartAiSessionAsync(DebateSide.PRO);

            // Turn 1 is the AI's, but the user's turn 0 has not been played yet.
            ApiResponseAssert.FailsWith(await _harness.AiSubmitsAsync(sessionId, 1), DebateErrorCodes.TurnOutOfOrder);

            ApiResponseAssert.Succeeds(await _harness.UserSubmitsAsync(UserA, sessionId));
            ApiResponseAssert.FailsWith(await _harness.AiSubmitsAsync(sessionId, 3), DebateErrorCodes.TurnOutOfOrder);
            Assert.Equal(1, _harness.ArgumentCount(sessionId));
        }

        [Fact]
        public async Task P2pSession_ReturnsNotAiSession()
        {
            int sessionId = await _harness.StartP2pSessionAsync(DebateSide.PRO);
            ApiResponseAssert.Succeeds(await _harness.UserSubmitsAsync(UserA, sessionId));

            ApiResponseAssert.FailsWith(await _harness.AiSubmitsAsync(sessionId, 1), DebateErrorCodes.NotAiSession);
            Assert.Equal(1, _harness.ArgumentCount(sessionId));
        }

        [Fact]
        public async Task UserNotInSession_ReturnsNotParticipant()
        {
            int sessionId = await _harness.StartAiSessionAsync(DebateSide.CON);

            ApiResponseAssert.FailsWith(await _harness.AiSubmitsAsync(sessionId, 0, userId: Outsider), DebateErrorCodes.NotParticipant);
            Assert.Equal(0, _harness.ArgumentCount(sessionId));
        }

        [Fact]
        public async Task UnknownSession_ReturnsSessionNotFound()
        {
            ApiResponseAssert.FailsWith(await _harness.AiSubmitsAsync(9999, 0), DebateErrorCodes.SessionNotFound);
        }

        [Fact]
        public async Task SessionNotStarted_ReturnsSessionNotInProgress()
        {
            var created = ApiResponseAssert.Succeeds(await _harness.NewService().CreateAiPracticeSessionAsync(UserA, new CreateAiPracticeSessionRequest
            {
                Title = "Motion",
                Topic = "Topic",
                UserSide = DebateSide.CON,
                IsAI = true
            }));

            ApiResponseAssert.FailsWith(await _harness.AiSubmitsAsync(created.SessionId, 0), DebateErrorCodes.SessionNotInProgress);
        }

        [Theory]
        [InlineData(null, 0)]
        [InlineData("   ", 0)]
        [InlineData("speech", null)]
        [InlineData("speech", -1)]
        [InlineData("speech", 6)]
        public async Task InvalidBody_ReturnsInvalidRequest(string? content, int? turnIndex)
        {
            int sessionId = await _harness.StartAiSessionAsync(DebateSide.CON);

            ApiResponseAssert.FailsWith(await _harness.AiSubmitsAsync(sessionId, turnIndex, content), DebateErrorCodes.InvalidRequest);
            Assert.Equal(0, _harness.ArgumentCount(sessionId));
        }

        [Fact]
        public async Task ContentTooLong_ReturnsInvalidRequest()
        {
            int sessionId = await _harness.StartAiSessionAsync(DebateSide.CON);

            ApiResponseAssert.FailsWith(await _harness.AiSubmitsAsync(sessionId, 0, new string('a', 10001)), DebateErrorCodes.InvalidRequest);
        }

        [Fact]
        public async Task SavedArgument_UsesAiParticipant_RoundAndTrimmedContent()
        {
            int sessionId = await _harness.StartAiSessionAsync(DebateSide.PRO);
            ApiResponseAssert.Succeeds(await _harness.UserSubmitsAsync(UserA, sessionId));

            var result = ApiResponseAssert.Succeeds(await _harness.AiSubmitsAsync(sessionId, 1, "  AI opening reply  "));

            Assert.Equal(1, result.TurnIndex);
            Assert.Equal("AI opening reply", result.Argument.Content);
            Assert.Equal(DebateStage.Opening, result.Argument.Stage);
            Assert.Equal(1, result.Argument.TurnOrder);
            Assert.Equal(2, result.Session.CurrentTurn!.TurnIndex);
            Assert.Equal(DebateSide.PRO, result.Session.CurrentTurnSide);
        }
    }
}
