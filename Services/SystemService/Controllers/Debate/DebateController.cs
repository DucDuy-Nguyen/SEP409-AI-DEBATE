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

        [HttpPost("2v2")]
        public async Task<IActionResult> Create2v2Session(
            [FromBody] Create2v2SessionRequest request, CancellationToken cancellationToken)
        {
            var userId = GetCurrentUserId();
            if (userId == null)
            {
                return Unauthorized(ApiResponse<object>.FailureResponse("Unauthorized access."));
            }

            var result = await _debateService.Create2v2SessionAsync(userId.Value, request, cancellationToken);
            if (!result.Success)
            {
                return BadRequest(result);
            }
            return Ok(result);
        }

        [HttpPost("{sessionId:int}/join-2v2")]
        public async Task<IActionResult> Join2v2Session(
            int sessionId, [FromBody] Join2v2SessionRequest request, CancellationToken cancellationToken)
        {
            var userId = GetCurrentUserId();
            if (userId == null)
            {
                return Unauthorized(ApiResponse<object>.FailureResponse("Unauthorized access."));
            }

            var result = await _debateService.Join2v2SessionAsync(userId.Value, sessionId, request, cancellationToken);
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

        [HttpPost("{sessionId:int}/switch-side")]
        public async Task<IActionResult> SwitchSide(int sessionId, CancellationToken cancellationToken)
        {
            var userId = GetCurrentUserId();
            if (userId == null)
            {
                return Unauthorized(ApiResponse<object>.FailureResponse("Unauthorized access."));
            }

            var result = await _debateService.SwitchSideAsync(userId.Value, sessionId, cancellationToken);
            if (!result.Success)
            {
                return BadRequest(result);
            }
            return Ok(result);
        }

        [HttpPost("{sessionId:int}/swap-request")]
        public async Task<IActionResult> SendSwapSideRequest(
            int sessionId, [FromBody] SendSwapSideRequest request, CancellationToken cancellationToken)
        {
            var userId = GetCurrentUserId();
            if (userId == null)
            {
                return Unauthorized(ApiResponse<object>.FailureResponse("Unauthorized access."));
            }

            var result = await _debateService.SendSwapSideRequestAsync(userId.Value, sessionId, request, cancellationToken);
            if (!result.Success)
            {
                return BadRequest(result);
            }
            return Ok(result);
        }

        [HttpPost("{sessionId:int}/swap-response")]
        public async Task<IActionResult> RespondSwapSideRequest(
            int sessionId, [FromBody] RespondSwapSideRequest request, CancellationToken cancellationToken)
        {
            var userId = GetCurrentUserId();
            if (userId == null)
            {
                return Unauthorized(ApiResponse<object>.FailureResponse("Unauthorized access."));
            }

            var result = await _debateService.RespondSwapSideRequestAsync(userId.Value, sessionId, request, cancellationToken);
            if (!result.Success)
            {
                return BadRequest(result);
            }
            return Ok(result);
        }

        [HttpGet("{sessionId:int}/swap-requests")]
        public async Task<IActionResult> GetPendingSwapRequests(int sessionId, CancellationToken cancellationToken)
        {
            var userId = GetCurrentUserId();
            if (userId == null)
            {
                return Unauthorized(ApiResponse<object>.FailureResponse("Unauthorized access."));
            }

            var result = await _debateService.GetPendingSwapRequestsAsync(userId.Value, sessionId, cancellationToken);
            return Ok(result);
        }

        [HttpPost("{sessionId:int}/start")]
        public async Task<IActionResult> StartDebateSession(int sessionId, CancellationToken cancellationToken)
        {
            var userId = GetCurrentUserId();
            if (userId == null)
            {
                return Unauthorized(ApiResponse<object>.FailureResponse("Unauthorized access."));
            }

            var result = await _debateService.StartDebateSessionAsync(userId.Value, sessionId, cancellationToken);
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
