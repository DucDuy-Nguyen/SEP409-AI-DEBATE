using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using System.Security.Claims;
using System.Threading;
using System.Threading.Tasks;
using SystemService.BLL.Common.Responses;
using SystemService.BLL.DTOs.Debate;
using SystemService.BLL.Services.Debate.Interfaces;

namespace SystemService.Controllers.Debate
{
    [ApiController]
    [Route("api/debate/challenges")]
    [Authorize]
    public class DebateChallengeController : ControllerBase
    {
        private readonly IDebateChallengeService _challengeService;

        public DebateChallengeController(IDebateChallengeService challengeService)
        {
            _challengeService = challengeService;
        }

        [HttpPost]
        public async Task<IActionResult> CreateChallenge(
            [FromBody] CreateChallengeRequest request, CancellationToken cancellationToken)
        {
            var userId = GetCurrentUserId();
            if (userId == null)
            {
                return Unauthorized(ApiResponse<object>.FailureResponse("Unauthorized access."));
            }

            var result = await _challengeService.CreateChallengeAsync(userId.Value, request, cancellationToken);
            if (!result.Success)
            {
                return BadRequest(result);
            }
            return Ok(result);
        }

        [HttpGet("received")]
        public async Task<IActionResult> GetReceivedChallenges(CancellationToken cancellationToken)
        {
            var userId = GetCurrentUserId();
            if (userId == null)
            {
                return Unauthorized(ApiResponse<object>.FailureResponse("Unauthorized access."));
            }

            var result = await _challengeService.GetReceivedChallengesAsync(userId.Value, cancellationToken);
            return Ok(result);
        }

        [HttpGet("sent")]
        public async Task<IActionResult> GetSentChallenges(CancellationToken cancellationToken)
        {
            var userId = GetCurrentUserId();
            if (userId == null)
            {
                return Unauthorized(ApiResponse<object>.FailureResponse("Unauthorized access."));
            }

            var result = await _challengeService.GetSentChallengesAsync(userId.Value, cancellationToken);
            return Ok(result);
        }

        [HttpGet("{challengeId:int}")]
        public async Task<IActionResult> GetChallengeById(int challengeId, CancellationToken cancellationToken)
        {
            var userId = GetCurrentUserId();
            if (userId == null)
            {
                return Unauthorized(ApiResponse<object>.FailureResponse("Unauthorized access."));
            }

            var result = await _challengeService.GetChallengeByIdAsync(userId.Value, challengeId, cancellationToken);
            if (!result.Success)
            {
                return BadRequest(result);
            }
            return Ok(result);
        }

        [HttpPost("{challengeId:int}/accept")]
        public async Task<IActionResult> AcceptChallenge(int challengeId, CancellationToken cancellationToken)
        {
            var userId = GetCurrentUserId();
            if (userId == null)
            {
                return Unauthorized(ApiResponse<object>.FailureResponse("Unauthorized access."));
            }

            var result = await _challengeService.AcceptChallengeAsync(userId.Value, challengeId, cancellationToken);
            if (!result.Success)
            {
                return BadRequest(result);
            }
            return Ok(result);
        }

        [HttpPost("{challengeId:int}/reject")]
        public async Task<IActionResult> RejectChallenge(int challengeId, CancellationToken cancellationToken)
        {
            var userId = GetCurrentUserId();
            if (userId == null)
            {
                return Unauthorized(ApiResponse<object>.FailureResponse("Unauthorized access."));
            }

            var result = await _challengeService.RejectChallengeAsync(userId.Value, challengeId, cancellationToken);
            if (!result.Success)
            {
                return BadRequest(result);
            }
            return Ok(result);
        }

        [HttpPost("{challengeId:int}/cancel")]
        public async Task<IActionResult> CancelChallenge(int challengeId, CancellationToken cancellationToken)
        {
            var userId = GetCurrentUserId();
            if (userId == null)
            {
                return Unauthorized(ApiResponse<object>.FailureResponse("Unauthorized access."));
            }

            var result = await _challengeService.CancelChallengeAsync(userId.Value, challengeId, cancellationToken);
            if (!result.Success)
            {
                return BadRequest(result);
            }
            return Ok(result);
        }

        #region Private Helpers

        private int? GetCurrentUserId()
        {
            var userIdClaim = User.FindFirstValue(ClaimTypes.NameIdentifier);
            if (int.TryParse(userIdClaim, out int userId))
            {
                return userId;
            }
            return null;
        }

        #endregion
    }
}
