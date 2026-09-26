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
    [Route("api/[controller]")]
    [Authorize]
    public class DebateController : ControllerBase
    {
        private readonly IDebateService _debateService;

        public DebateController(IDebateService debateService)
        {
            _debateService = debateService;
        }

        [HttpPost("ai-practice")]
        public async Task<IActionResult> CreateAiPracticeSession(
            [FromBody] CreateAiPracticeSessionRequest request, CancellationToken cancellationToken)
        {
            var userId = GetCurrentUserId();
            if (userId == null)
            {
                return Unauthorized(ApiResponse<object>.FailureResponse("Unauthorized access."));
            }

            var result = await _debateService.CreateAiPracticeSessionAsync(userId.Value, request, cancellationToken);
            if (!result.Success)
            {
                return BadRequest(result);
            }
            return Ok(result);
        }

        [HttpPost("p2p")]
        public async Task<IActionResult> CreateP2pSession(
            [FromBody] CreateP2pSessionRequest request, CancellationToken cancellationToken)
        {
            var userId = GetCurrentUserId();
            if (userId == null)
            {
                return Unauthorized(ApiResponse<object>.FailureResponse("Unauthorized access."));
            }

            var result = await _debateService.CreateP2pSessionAsync(userId.Value, request, cancellationToken);
            if (!result.Success)
            {
                return BadRequest(result);
            }
            return Ok(result);
        }

        [HttpPost("{sessionId:int}/join")]
        public async Task<IActionResult> JoinP2pSession(
            int sessionId, [FromBody] JoinSessionRequest request, CancellationToken cancellationToken)
        {
            var userId = GetCurrentUserId();
            if (userId == null)
            {
                return Unauthorized(ApiResponse<object>.FailureResponse("Unauthorized access."));
            }

            var result = await _debateService.JoinP2pSessionAsync(userId.Value, sessionId, request, cancellationToken);
            if (!result.Success)
            {
                return BadRequest(result);
            }
            return Ok(result);
        }

        [HttpGet("{sessionId:int}")]
        public async Task<IActionResult> GetSessionDetails(int sessionId, CancellationToken cancellationToken)
        {
            var userId = GetCurrentUserId() ?? 0;
            var result = await _debateService.GetSessionDetailsAsync(userId, sessionId, cancellationToken);
            if (!result.Success)
            {
                return NotFound(result);
            }
            return Ok(result);
        }

        [HttpPost("{sessionId:int}/arguments")]
        public async Task<IActionResult> SubmitArgument(
            int sessionId, [FromBody] SubmitArgumentRequest request, CancellationToken cancellationToken)
        {
            var userId = GetCurrentUserId();
            if (userId == null)
            {
                return Unauthorized(ApiResponse<object>.FailureResponse("Unauthorized access."));
            }

            var result = await _debateService.SubmitArgumentAsync(userId.Value, sessionId, request, cancellationToken);
            if (!result.Success)
            {
                return BadRequest(result);
            }
            return Ok(result);
        }

        [HttpGet("{sessionId:int}/transcript")]
        public async Task<IActionResult> GetTranscript(int sessionId, CancellationToken cancellationToken)
        {
            var userId = GetCurrentUserId() ?? 0;
            var result = await _debateService.GetTranscriptAsync(userId, sessionId, cancellationToken);
            if (!result.Success)
            {
                return NotFound(result);
            }
            return Ok(result);
        }


        [HttpGet("my-history")]
        public async Task<IActionResult> GetUserHistory(CancellationToken cancellationToken)
        {
            var userId = GetCurrentUserId();
            if (userId == null)
            {
                return Unauthorized(ApiResponse<object>.FailureResponse("Unauthorized access."));
            }

            var result = await _debateService.GetUserHistoryAsync(userId.Value, cancellationToken);
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
