using System.Security.Claims;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using SystemService.BLL.Common.Debate;
using SystemService.BLL.Common.Responses;
using SystemService.BLL.Services.Debate.Interfaces;

namespace SystemService.Controllers.Debate
{
    /// <summary>Team call of a 2v2 side during the preparation minute; the signalling itself goes through DebateHub.</summary>
    [ApiController]
    [Route("api/debate")]
    [Authorize]
    public class TeamCallController : ControllerBase
    {
        private readonly ITeamCallService _teamCallService;

        public TeamCallController(ITeamCallService teamCallService)
        {
            _teamCallService = teamCallService;
        }

        // STUN + TURN (short-lived credentials) for RTCPeerConnection, for a debater who has a human teammate
        [HttpGet("{sessionId:int}/ice-servers")]
        public async Task<IActionResult> GetIceServers(int sessionId, CancellationToken cancellationToken)
        {
            if (!int.TryParse(User.FindFirstValue(ClaimTypes.NameIdentifier), out int userId))
            {
                return Unauthorized(ApiResponse<object>.FailureResponse("Unauthorized access."));
            }

            var result = await _teamCallService.GetIceServersAsync(userId, sessionId, cancellationToken);
            if (result.Success)
            {
                return Ok(result);
            }
            return (result.Errors as ApiErrorDetail)?.Code switch
            {
                DebateErrorCodes.SessionNotFound => NotFound(result),
                DebateErrorCodes.NotParticipant or DebateErrorCodes.NoTeammate => StatusCode(StatusCodes.Status403Forbidden, result),
                DebateErrorCodes.SessionNotInProgress => Conflict(result),
                _ => BadRequest(result)
            };
        }
    }
}
