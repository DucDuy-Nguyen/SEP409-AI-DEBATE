using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using PayOS.Models.Webhooks;
using System.Security.Claims;
using System.Threading;
using System.Threading.Tasks;
using SystemService.BLL.Common.Responses;
using SystemService.BLL.DTOs.Payment;
using SystemService.BLL.Services.Payment.Interfaces;

namespace SystemService.Controllers.Payment
{
    [ApiController]
    [Route("api/payments")]
    public class PaymentsController : ControllerBase
    {
        private readonly IPaymentService _paymentService;

        public PaymentsController(IPaymentService paymentService)
        {
            _paymentService = paymentService;
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

        [Authorize]
        [HttpPost("top-up")]
        public async Task<IActionResult> CreateTopUpPayment([FromBody] TopUpRequest request, CancellationToken cancellationToken)
        {
            var userId = GetCurrentUserId();
            if (!userId.HasValue)
            {
                return Unauthorized(ApiResponse<PaymentLinkResponse>.FailureResponse("Unauthorized access."));
            }

            var result = await _paymentService.CreateTopUpPaymentAsync(userId.Value, request, cancellationToken);
            if (!result.Success)
            {
                return BadRequest(result);
            }
            return Ok(result);
        }

        [Authorize]
        [HttpGet("{paymentId:long}")]
        public async Task<IActionResult> GetPaymentStatus(long paymentId, CancellationToken cancellationToken)
        {
            var userId = GetCurrentUserId();
            if (!userId.HasValue)
            {
                return Unauthorized(ApiResponse<PaymentStatusResponse>.FailureResponse("Unauthorized access."));
            }

            var result = await _paymentService.GetPaymentStatusAsync(userId.Value, paymentId, cancellationToken);
            if (!result.Success)
            {
                if (result.Message == "Access denied.")
                {
                    return Forbid();
                }
                if (result.Message == "Payment not found.")
                {
                    return NotFound(result);
                }
                return BadRequest(result);
            }
            return Ok(result);
        }

        [AllowAnonymous]
        [HttpPost("payos/webhook")]
        public async Task<IActionResult> PayOSWebhook([FromBody] Webhook webhook, CancellationToken cancellationToken)
        {
            var result = await _paymentService.ProcessPayOSWebhookAsync(webhook, cancellationToken);
            if (!result.Success)
            {
                return BadRequest(result);
            }
            return Ok(result);
        }
    }
}
