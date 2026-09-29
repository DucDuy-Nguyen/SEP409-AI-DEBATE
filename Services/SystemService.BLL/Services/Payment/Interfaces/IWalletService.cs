using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using SystemService.BLL.Common.Responses;
using SystemService.BLL.DTOs.Payment;

namespace SystemService.BLL.Services.Payment.Interfaces
{
    public interface IWalletService
    {
        Task<ApiResponse<WalletResponse>> GetMyWalletAsync(int userId, CancellationToken cancellationToken = default);
        Task<ApiResponse<List<WalletTransactionResponse>>> GetMyTransactionsAsync(int userId, int page = 1, int pageSize = 20, CancellationToken cancellationToken = default);
    }
}
