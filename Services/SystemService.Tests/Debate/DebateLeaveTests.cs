using System.Security.Claims;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using SystemService.BLL.Common.Debate;
using SystemService.BLL.DTOs.Debate;
using SystemService.Controllers.Debate;
using SystemService.DAL.Entities.Debate.Enums;
using static SystemService.Tests.Debate.DebateTestHarness;

namespace SystemService.Tests.Debate
{
    public class DebateLeaveTests : IDisposable
    {
        private readonly DebateTestHarness _harness = new();

        public void Dispose() => _harness.Dispose();

        [Fact]
        public async Task InProgressAiSession_BecomesCancelled_WithEndTime()
        {
            int sessionId = await _harness.StartAiSessionAsync(DebateSide.PRO);
            ApiResponseAssert.Succeeds(await _harness.UserSubmitsAsync(UserA, sessionId));

            var result = ApiResponseAssert.Succeeds(await LeaveAsync(UserA, sessionId));

            Assert.Equal(SessionStatus.Cancelled, result.Status);
            var stored = _harness.LoadSession(sessionId);
            Assert.Equal(SessionStatus.Cancelled, stored.Status);
            Assert.NotNull(stored.EndTime);
            Assert.Equal(1, _harness.ArgumentCount(sessionId));
        }

        [Fact]
        public async Task WaitingSession_LeftByHost_BecomesCancelled()
        {
            int sessionId = await CreateWaitingP2pAsync();

            ApiResponseAssert.Succeeds(await LeaveAsync(UserA, sessionId));

            Assert.Equal(SessionStatus.Cancelled, _harness.LoadSession(sessionId).Status);
            var joined = await _harness.NewService().JoinP2pSessionAsync(UserB, sessionId, new JoinSessionRequest());
            Assert.False(joined.Success);
        }

        [Fact]
        public async Task P2p_OnePlayerLeaving_CancelsItForBoth()
        {
            int sessionId = await _harness.StartP2pSessionAsync(DebateSide.PRO);
            ApiResponseAssert.Succeeds(await _harness.UserSubmitsAsync(UserA, sessionId));

            ApiResponseAssert.Succeeds(await LeaveAsync(UserB, sessionId));

            ApiResponseAssert.FailsWith(await _harness.UserSubmitsAsync(UserB, sessionId), DebateErrorCodes.SessionNotInProgress);
            ApiResponseAssert.FailsWith(await _harness.UserSubmitsAsync(UserA, sessionId), DebateErrorCodes.SessionNotInProgress);
            Assert.Equal(SessionStatus.Cancelled, await HistoryStatusAsync(UserA, sessionId));
            Assert.Equal(SessionStatus.Cancelled, await HistoryStatusAsync(UserB, sessionId));
        }

        [Theory]
        [InlineData(false)]
        [InlineData(true)]
        public async Task TwoVsTwo_TreatedLikeOneVsOne(bool isAi)
        {
            var created = ApiResponseAssert.Succeeds(await _harness.NewService().Create2v2SessionAsync(UserA, new Create2v2SessionRequest
            {
                Title = "Motion",
                Topic = "Topic",
                UserSide = DebateSide.PRO,
                IsAI = isAi
            }));

            ApiResponseAssert.Succeeds(await LeaveAsync(UserA, created.SessionId));

            Assert.Equal(SessionStatus.Cancelled, _harness.LoadSession(created.SessionId).Status);
        }

        [Fact]
        public async Task LateAiArgument_AfterLeaving_IsRejected_AndNotStored()
        {
            int sessionId = await _harness.StartAiSessionAsync(DebateSide.PRO);
            ApiResponseAssert.Succeeds(await _harness.UserSubmitsAsync(UserA, sessionId));
            ApiResponseAssert.Succeeds(await LeaveAsync(UserA, sessionId));

            ApiResponseAssert.FailsWith(await _harness.AiSubmitsAsync(sessionId, 1), DebateErrorCodes.SessionNotInProgress);
            Assert.Equal(1, _harness.ArgumentCount(sessionId));
        }

        [Fact]
        public async Task LeavingTwice_Succeeds_AndKeepsTheFirstEndTime()
        {
            int sessionId = await _harness.StartAiSessionAsync(DebateSide.PRO);
            ApiResponseAssert.Succeeds(await LeaveAsync(UserA, sessionId));
            var firstEnd = _harness.LoadSession(sessionId).EndTime;

            var second = ApiResponseAssert.Succeeds(await LeaveAsync(UserA, sessionId));

            Assert.Equal(SessionStatus.Cancelled, second.Status);
            Assert.Equal(firstEnd, _harness.LoadSession(sessionId).EndTime);
        }

        [Fact]
        public async Task CompletedSession_IsRejected_AndStaysCompleted()
        {
            int sessionId = await PlayCompletedAiSessionAsync();

            ApiResponseAssert.FailsWith(await LeaveAsync(UserA, sessionId), DebateErrorCodes.SessionCompleted);

            Assert.Equal(SessionStatus.Completed, _harness.LoadSession(sessionId).Status);
        }

        [Fact]
        public async Task NonParticipant_IsRejected_AndSessionIsUntouched()
        {
            int sessionId = await _harness.StartAiSessionAsync(DebateSide.PRO);

            ApiResponseAssert.FailsWith(await LeaveAsync(Outsider, sessionId), DebateErrorCodes.NotParticipant);

            Assert.Equal(SessionStatus.InProgress, _harness.LoadSession(sessionId).Status);
        }

        // ---- HTTP status ----

        [Fact]
        public async Task Controller_MapsEachOutcome()
        {
            int sessionId = await _harness.StartAiSessionAsync(DebateSide.PRO);
            int completedId = await PlayCompletedAiSessionAsync();

            Assert.Equal(StatusCodes.Status404NotFound, StatusOf(await PostAsync(UserA, 9999)));
            Assert.Equal(StatusCodes.Status403Forbidden, StatusOf(await PostAsync(Outsider, sessionId)));
            Assert.Equal(StatusCodes.Status409Conflict, StatusOf(await PostAsync(UserA, completedId)));
            Assert.Equal(StatusCodes.Status200OK, StatusOf(await PostAsync(UserA, sessionId)));
            Assert.Equal(StatusCodes.Status200OK, StatusOf(await PostAsync(UserA, sessionId)));
        }

        private Task<SystemService.BLL.Common.Responses.ApiResponse<DebateSessionResponse>> LeaveAsync(int userId, int sessionId)
        {
            return _harness.NewService().LeaveSessionAsync(userId, sessionId);
        }

        private async Task<int> CreateWaitingP2pAsync()
        {
            var created = ApiResponseAssert.Succeeds(await _harness.NewService().CreateP2pSessionAsync(UserA, new CreateP2pSessionRequest
            {
                Title = "Motion",
                Topic = "Topic",
                UserSide = DebateSide.PRO,
                IsAI = false
            }));
            return created.SessionId;
        }

        private async Task<int> PlayCompletedAiSessionAsync()
        {
            int sessionId = await _harness.StartAiSessionAsync(DebateSide.CON);
            ApiResponseAssert.Succeeds(await _harness.AiSubmitsAsync(sessionId, 0));
            ApiResponseAssert.Succeeds(await _harness.UserSubmitsAsync(UserA, sessionId));
            ApiResponseAssert.Succeeds(await _harness.AiSubmitsAsync(sessionId, 2));
            ApiResponseAssert.Succeeds(await _harness.UserSubmitsAsync(UserA, sessionId));
            ApiResponseAssert.Succeeds(await _harness.UserSubmitsAsync(UserA, sessionId));
            ApiResponseAssert.Succeeds(await _harness.AiSubmitsAsync(sessionId, 5));
            return sessionId;
        }

        private async Task<SessionStatus> HistoryStatusAsync(int userId, int sessionId)
        {
            var history = ApiResponseAssert.Succeeds(await _harness.NewService().GetUserHistoryAsync(userId));
            return history.Single(h => h.SessionId == sessionId).Status;
        }

        private Task<IActionResult> PostAsync(int userId, int sessionId)
        {
            var controller = new DebateController(_harness.NewService())
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
            return controller.LeaveSession(sessionId, CancellationToken.None);
        }

        private static int StatusOf(IActionResult result)
        {
            return Assert.IsAssignableFrom<ObjectResult>(result).StatusCode ?? StatusCodes.Status200OK;
        }
    }
}
