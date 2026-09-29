using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using SystemService.BLL.Common.Responses;
using SystemService.BLL.DTOs.Payment;
using SystemService.BLL.Services.Payment.Interfaces;
using SystemService.DAL.Repositories.Payment.Interfaces;

namespace SystemService.BLL.Services.Payment.Implementations
{
    public class WalletService : IWalletService
    {
        private readonly IWalletRepository _walletRepository;

        public WalletService(IWalletRepository walletRepository)
        {
            _walletRepository = walletRepository;
        }

        public async Task<ApiResponse<WalletResponse>> GetMyWalletAsync(int userId, CancellationToken cancellationToken = default)
        {
            var wallet = await _walletRepository.GetOrCreateWalletByUserIdAsync(userId, cancellationToken);

            var response = new WalletResponse
            {
                WalletId = wallet.WalletId,
                Balance = wallet.Balance,
                UpdatedAt = wallet.UpdatedAt
            };

            return ApiResponse<WalletResponse>.SuccessResponse(response);
        }

        public async Task<ApiResponse<List<WalletTransactionResponse>>> GetMyTransactionsAsync(int userId, int page = 1, int pageSize = 20, CancellationToken cancellationToken = default)
        {
            var wallet = await _walletRepository.GetOrCreateWalletByUserIdAsync(userId, cancellationToken);

            var (items, totalCount) = await _walletRepository.GetTransactionsAsync(wallet.WalletId, page, pageSize, cancellationToken);

            var response = items.Select(t => new WalletTransactionResponse
            {
                WalletTransactionId = t.WalletTransactionId,
                TransactionType = t.TransactionType,
                SourceType = t.SourceType,
                Amount = t.Amount,
                BalanceBefore = t.BalanceBefore,
                BalanceAfter = t.BalanceAfter,
                ReferenceType = t.ReferenceType,
                ReferenceId = t.ReferenceId,
                Description = t.Description,
                CreatedAt = t.CreatedAt
            }).ToList();

            return ApiResponse<List<WalletTransactionResponse>>.SuccessResponse(response, $"Page {page} of transactions (Total: {totalCount})");
        }
    }
}
