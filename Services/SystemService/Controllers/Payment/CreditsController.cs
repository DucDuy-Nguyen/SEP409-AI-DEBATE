using System.Security.Claims;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using SystemService.BLL.Common.Debate;
using SystemService.BLL.Common.Responses;
using SystemService.BLL.DTOs.Payment;
using SystemService.BLL.Services.Payment.Interfaces;

namespace SystemService.Controllers.Payment
{
    [ApiController]
    [Route("api/credits")]
    public class CreditsController : ControllerBase
    {
        private readonly ICreditService _creditService;

        public CreditsController(ICreditService creditService)
        {
            _creditService = creditService;
        }

        [AllowAnonymous]
        [HttpGet("prices")]
        public async Task<IActionResult> GetPrices(CancellationToken cancellationToken)
        {
            var result = await _creditService.GetPricesAsync(cancellationToken);
            if (!result.Success)
            {
                return BadRequest(result);
            }
            return Ok(result);
        }

        [AllowAnonymous]
        [HttpGet("competition-price")]
        public async Task<IActionResult> GetCompetitionPrice(
            [FromQuery] string competitionType = "INDIVIDUAL",
            [FromQuery] int? maxParticipants = null,
            [FromQuery] int? maxTeams = null,
            CancellationToken cancellationToken = default)
        {
            var result = await _creditService.GetCompetitionPriceQuoteAsync(
                competitionType, maxParticipants, maxTeams, cancellationToken);

            if (!result.Success)
            {
                return BadRequest(result);
            }
            return Ok(result);
        }

        [Authorize]
        [HttpPost("hint/argument")]
        public async Task<IActionResult> RequestArgumentHint(
            [FromBody] AiHintRequest request,
            CancellationToken cancellationToken)
        {
            var userId = GetCurrentUserId();
            if (!userId.HasValue)
            {
                return Unauthorized(ApiResponse<AiHintResponse>.FailureResponse("Unauthorized access."));
            }

            if (request != null && string.IsNullOrWhiteSpace(request.RequestId)
                && Request.Headers.TryGetValue("X-Idempotency-Key", out var headerKey))
            {
                request.RequestId = headerKey.ToString();
            }

            var result = await _creditService.RequestArgumentHintAsync(userId.Value, request!, cancellationToken);
            if (!result.Success)
            {
                return MapFailure(result);
            }
            return Ok(result);
        }

        private int? GetCurrentUserId()
        {
            var userIdClaim = User.FindFirstValue(ClaimTypes.NameIdentifier);
            if (int.TryParse(userIdClaim, out int userId))
            {
                return userId;
            }
            return null;
        }

        private IActionResult MapFailure<T>(ApiResponse<T> result)
        {
            if (result.Errors is InsufficientCreditsErrorDetail insufficient)
            {
                return BadRequest(new ApiResponse<InsufficientCreditsData>
                {
                    Success = false,
                    Code = InsufficientCreditsErrorDetail.ErrorCode,
                    Message = result.Message,
                    Data = new InsufficientCreditsData
                    {
                        RequiredCredits = insufficient.RequiredCredits,
                        CurrentCredits = insufficient.CurrentCredits,
                        MissingCredits = insufficient.MissingCredits
                    },
                    Errors = insufficient
                });
            }

            var code = (result.Errors as ApiErrorDetail)?.Code ?? result.Code;
            return code switch
            {
                DebateErrorCodes.SessionNotFound => NotFound(result),
                DebateErrorCodes.NotParticipant => StatusCode(StatusCodes.Status403Forbidden, result),
                "DUPLICATE_REQUEST" => Conflict(result),
                "AI_HINT_FAILED" => StatusCode(StatusCodes.Status502BadGateway, result),
                _ => BadRequest(result)
            };
        }
    }
}
