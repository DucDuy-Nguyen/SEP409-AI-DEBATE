using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using System.Security.Claims;
using System.Threading;
using System.Threading.Tasks;
using SystemService.BLL.Common.Responses;
using SystemService.BLL.DTOs.Competition.Team;
using SystemService.BLL.Services.Competition.Interfaces;

namespace SystemService.Controllers.Competition
{
    [ApiController]
    [Route("api/competitions/{id}")]
    public class CompetitionTeamRequestsController : ControllerBase
    {
        private readonly ICompetitionTeamRequestService _requestService;

        public CompetitionTeamRequestsController(ICompetitionTeamRequestService requestService)
        {
            _requestService = requestService;
        }

        [Authorize]
        [HttpPost("teams/{teamId}/invitations")]
        public async Task<IActionResult> SendInvitation(int id, int teamId, [FromBody] SendTeamInvitationRequest request, CancellationToken cancellationToken)
        {
            var userIdClaim = User.FindFirstValue(ClaimTypes.NameIdentifier);
            if (!int.TryParse(userIdClaim, out int captainUserId))
            {
                return Unauthorized(ApiResponse<CompetitionTeamRequestResponse>.FailureResponse("Unauthorized access."));
            }

            var result = await _requestService.SendInvitationAsync(id, teamId, captainUserId, request, cancellationToken);
            if (!result.Success)
            {
                return BadRequest(result);
            }
            return Ok(result);
        }

        [Authorize]
        [HttpGet("teams/invitations/me")]
        public async Task<IActionResult> GetMyInvitations(int id, CancellationToken cancellationToken)
        {
            var userIdClaim = User.FindFirstValue(ClaimTypes.NameIdentifier);
            if (!int.TryParse(userIdClaim, out int currentUserId))
            {
                return Unauthorized(ApiResponse<object>.FailureResponse("Unauthorized access."));
            }

            var result = await _requestService.GetMyInvitationsAsync(id, currentUserId, cancellationToken);
            return Ok(result);
        }

        [Authorize]
        [HttpPost("teams/invitations/{requestId}/accept")]
        public async Task<IActionResult> AcceptInvitation(int id, long requestId, CancellationToken cancellationToken)
        {
            var userIdClaim = User.FindFirstValue(ClaimTypes.NameIdentifier);
            if (!int.TryParse(userIdClaim, out int currentUserId))
            {
                return Unauthorized(ApiResponse<object>.FailureResponse("Unauthorized access."));
            }

            var result = await _requestService.AcceptInvitationAsync(id, requestId, currentUserId, cancellationToken);
            if (!result.Success)
            {
                return BadRequest(result);
            }
            return Ok(result);
        }

        [Authorize]
        [HttpPost("teams/invitations/{requestId}/reject")]
        public async Task<IActionResult> RejectInvitation(int id, long requestId, [FromBody] RejectTeamRequestDto request, CancellationToken cancellationToken)
        {
            var userIdClaim = User.FindFirstValue(ClaimTypes.NameIdentifier);
            if (!int.TryParse(userIdClaim, out int currentUserId))
            {
                return Unauthorized(ApiResponse<object>.FailureResponse("Unauthorized access."));
            }

            var result = await _requestService.RejectInvitationAsync(id, requestId, currentUserId, request, cancellationToken);
            if (!result.Success)
            {
                return BadRequest(result);
            }
            return Ok(result);
        }

        [Authorize]
        [HttpPost("teams/{teamId}/join-requests")]
        public async Task<IActionResult> CreateJoinRequest(int id, int teamId, CancellationToken cancellationToken)
        {
            var userIdClaim = User.FindFirstValue(ClaimTypes.NameIdentifier);
            if (!int.TryParse(userIdClaim, out int currentUserId))
            {
                return Unauthorized(ApiResponse<CompetitionTeamRequestResponse>.FailureResponse("Unauthorized access."));
            }

            var result = await _requestService.CreateJoinRequestAsync(id, teamId, currentUserId, cancellationToken);
            if (!result.Success)
            {
                return BadRequest(result);
            }
            return Ok(result);
        }

        [Authorize]
        [HttpGet("teams/{teamId}/join-requests")]
        public async Task<IActionResult> GetTeamJoinRequests(int id, int teamId, CancellationToken cancellationToken)
        {
            var userIdClaim = User.FindFirstValue(ClaimTypes.NameIdentifier);
            if (!int.TryParse(userIdClaim, out int captainUserId))
            {
                return Unauthorized(ApiResponse<object>.FailureResponse("Unauthorized access."));
            }

            var result = await _requestService.GetTeamJoinRequestsAsync(id, teamId, captainUserId, cancellationToken);
            if (!result.Success)
            {
                return BadRequest(result);
            }
            return Ok(result);
        }

        [Authorize]
        [HttpPost("teams/{teamId}/join-requests/{requestId}/approve")]
        public async Task<IActionResult> ApproveJoinRequest(int id, int teamId, long requestId, CancellationToken cancellationToken)
        {
            var userIdClaim = User.FindFirstValue(ClaimTypes.NameIdentifier);
            if (!int.TryParse(userIdClaim, out int captainUserId))
            {
                return Unauthorized(ApiResponse<object>.FailureResponse("Unauthorized access."));
            }

            var result = await _requestService.ApproveJoinRequestAsync(id, teamId, requestId, captainUserId, cancellationToken);
            if (!result.Success)
            {
                return BadRequest(result);
            }
            return Ok(result);
        }

        [Authorize]
        [HttpPost("teams/{teamId}/join-requests/{requestId}/reject")]
        public async Task<IActionResult> RejectJoinRequest(int id, int teamId, long requestId, [FromBody] RejectTeamRequestDto request, CancellationToken cancellationToken)
        {
            var userIdClaim = User.FindFirstValue(ClaimTypes.NameIdentifier);
            if (!int.TryParse(userIdClaim, out int captainUserId))
            {
                return Unauthorized(ApiResponse<object>.FailureResponse("Unauthorized access."));
            }

            var result = await _requestService.RejectJoinRequestAsync(id, teamId, requestId, captainUserId, request, cancellationToken);
            if (!result.Success)
            {
                return BadRequest(result);
            }
            return Ok(result);
        }
    }
}
