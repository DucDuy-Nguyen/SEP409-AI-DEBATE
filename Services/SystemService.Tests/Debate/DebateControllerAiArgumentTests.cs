using System.Security.Claims;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using SystemService.BLL.DTOs.Debate;
using SystemService.Controllers.Debate;
using SystemService.DAL.Entities.Debate.Enums;
using static SystemService.Tests.Debate.DebateTestHarness;

namespace SystemService.Tests.Debate
{
    public class DebateControllerAiArgumentTests : IDisposable
    {
        private readonly DebateTestHarness _harness = new();

        public void Dispose() => _harness.Dispose();

        [Fact]
        public async Task Success_Returns200()
        {
            int sessionId = await _harness.StartAiSessionAsync(DebateSide.CON);

            var result = await PostAsync(UserA, sessionId, 0);

            Assert.Equal(StatusCodes.Status200OK, StatusOf(result));
        }

        [Fact]
        public async Task UnknownSession_Returns404()
        {
            Assert.Equal(StatusCodes.Status404NotFound, StatusOf(await PostAsync(UserA, 9999, 0)));
        }

        [Fact]
        public async Task NonParticipant_Returns403()
        {
            int sessionId = await _harness.StartAiSessionAsync(DebateSide.CON);

            Assert.Equal(StatusCodes.Status403Forbidden, StatusOf(await PostAsync(Outsider, sessionId, 0)));
        }

        [Fact]
        public async Task OutOfOrderTurn_Returns409()
        {
            int sessionId = await _harness.StartAiSessionAsync(DebateSide.CON);

            Assert.Equal(StatusCodes.Status409Conflict, StatusOf(await PostAsync(UserA, sessionId, 2)));
        }

        [Fact]
        public async Task UserTurnOrP2p_Returns400()
        {
            int aiSessionId = await _harness.StartAiSessionAsync(DebateSide.CON);
            int p2pSessionId = await _harness.StartP2pSessionAsync(DebateSide.PRO);

            Assert.Equal(StatusCodes.Status400BadRequest, StatusOf(await PostAsync(UserA, aiSessionId, 1)));
            Assert.Equal(StatusCodes.Status400BadRequest, StatusOf(await PostAsync(UserA, p2pSessionId, 0)));
        }

        private Task<IActionResult> PostAsync(int userId, int sessionId, int turnIndex)
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
            return controller.SubmitAiArgument(sessionId, new SubmitAiArgumentRequest { Content = "AI speech", TurnIndex = turnIndex }, CancellationToken.None);
        }

        private static int StatusOf(IActionResult result)
        {
            return Assert.IsAssignableFrom<ObjectResult>(result).StatusCode ?? StatusCodes.Status200OK;
        }
    }
}
