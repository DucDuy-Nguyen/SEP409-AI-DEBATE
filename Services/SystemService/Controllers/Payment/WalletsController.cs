using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using System.Collections.Generic;
using System.Security.Claims;
using System.Threading;
using System.Threading.Tasks;
using SystemService.BLL.Common.Responses;
using SystemService.BLL.DTOs.Payment;
using SystemService.BLL.Services.Payment.Interfaces;

namespace SystemService.Controllers.Payment
{
    [ApiController]
    [Route("api/wallets")]
    [Authorize]
    public class WalletsController : ControllerBase
    {
        private readonly IWalletService _walletService;

        public WalletsController(IWalletService walletService)
        {
            _walletService = walletService;
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

        [HttpGet("me")]
        public async Task<IActionResult> GetMyWallet(CancellationToken cancellationToken)
        {
            var userId = GetCurrentUserId();
            if (!userId.HasValue)
            {
                return Unauthorized(ApiResponse<WalletResponse>.FailureResponse("Unauthorized access."));
            }

            var result = await _walletService.GetMyWalletAsync(userId.Value, cancellationToken);
            if (!result.Success)
            {
                return BadRequest(result);
            }
            return Ok(result);
        }

        [HttpGet("me/transactions")]
        public async Task<IActionResult> GetMyTransactions(
            [FromQuery] int page = 1,
            [FromQuery] int pageSize = 20,
            CancellationToken cancellationToken = default)
        {
            var userId = GetCurrentUserId();
            if (!userId.HasValue)
            {
                return Unauthorized(ApiResponse<List<WalletTransactionResponse>>.FailureResponse("Unauthorized access."));
            }

            var result = await _walletService.GetMyTransactionsAsync(userId.Value, page, pageSize, cancellationToken);
            if (!result.Success)
            {
                return BadRequest(result);
            }
            return Ok(result);
        }
    }
}
