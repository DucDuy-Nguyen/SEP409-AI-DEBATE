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
    [Route("api/competitions/{id}/teams")]
    public class CompetitionTeamsController : ControllerBase
    {
        private readonly ICompetitionTeamService _teamService;

        public CompetitionTeamsController(ICompetitionTeamService teamService)
        {
            _teamService = teamService;
        }

        [Authorize]
        [HttpPost]
        public async Task<IActionResult> CreateTeam(int id, [FromBody] CreateCompetitionTeamRequest request, CancellationToken cancellationToken)
        {
            var userIdClaim = User.FindFirstValue(ClaimTypes.NameIdentifier);
            if (!int.TryParse(userIdClaim, out int userId))
            {
                return Unauthorized(ApiResponse<CompetitionTeamResponse>.FailureResponse("Unauthorized access."));
            }

            var result = await _teamService.CreateTeamAsync(id, userId, request, cancellationToken);
            if (!result.Success)
            {
                return BadRequest(result);
            }
            return Ok(result);
        }

        [HttpGet]
        public async Task<IActionResult> GetList(int id, CancellationToken cancellationToken)
        {
            var result = await _teamService.GetListAsync(id, cancellationToken);
            return Ok(result);
        }

        [HttpGet("{teamId}")]
        public async Task<IActionResult> GetById(int id, int teamId, CancellationToken cancellationToken)
        {
            var result = await _teamService.GetByIdAsync(id, teamId, cancellationToken);
            if (!result.Success)
            {
                return NotFound(result);
            }
            return Ok(result);
        }

        [Authorize]
        [HttpPost("{teamId}/members")]
        public async Task<IActionResult> AddMember(int id, int teamId, [FromBody] AddCompetitionTeamMemberRequest request, CancellationToken cancellationToken)
        {
            var userIdClaim = User.FindFirstValue(ClaimTypes.NameIdentifier);
            if (!int.TryParse(userIdClaim, out int userId))
            {
                return Unauthorized(ApiResponse<object>.FailureResponse("Unauthorized access."));
            }

            var result = await _teamService.AddMemberAsync(id, teamId, userId, request, cancellationToken);
            if (!result.Success)
            {
                return BadRequest(result);
            }
            return Ok(result);
        }

        [Authorize]
        [HttpDelete("{teamId}/members/{userId}")]
        public async Task<IActionResult> RemoveMember(int id, int teamId, int userId, CancellationToken cancellationToken)
        {
            var userIdClaim = User.FindFirstValue(ClaimTypes.NameIdentifier);
            if (!int.TryParse(userIdClaim, out int currentUserId))
            {
                return Unauthorized(ApiResponse<object>.FailureResponse("Unauthorized access."));
            }

            var result = await _teamService.RemoveMemberAsync(id, teamId, userId, currentUserId, cancellationToken);
            if (!result.Success)
            {
                return BadRequest(result);
            }
            return Ok(result);
        }

        [Authorize]
        [HttpPost("{teamId}/withdraw")]
        public async Task<IActionResult> WithdrawTeam(int id, int teamId, CancellationToken cancellationToken)
        {
            var userIdClaim = User.FindFirstValue(ClaimTypes.NameIdentifier);
            if (!int.TryParse(userIdClaim, out int userId))
            {
                return Unauthorized(ApiResponse<object>.FailureResponse("Unauthorized access."));
            }

            var result = await _teamService.WithdrawTeamAsync(id, teamId, userId, cancellationToken);
            if (!result.Success)
            {
                return BadRequest(result);
            }
            return Ok(result);
        }
    }
}
