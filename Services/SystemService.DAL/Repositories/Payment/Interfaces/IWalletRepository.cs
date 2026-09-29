using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using SystemService.DAL.Entities.Payment;

namespace SystemService.DAL.Repositories.Payment.Interfaces
{
    public interface IWalletRepository
    {
        Task<Wallet?> GetByUserIdAsync(int userId, CancellationToken cancellationToken = default);
        Task<Wallet?> GetByIdAsync(int walletId, CancellationToken cancellationToken = default);
        Task<Wallet?> GetByIdForUpdateAsync(int walletId, CancellationToken cancellationToken = default);
        Task<Wallet?> GetByUserIdForUpdateAsync(int userId, CancellationToken cancellationToken = default);
        Task<Wallet> CreateWalletAsync(Wallet wallet, CancellationToken cancellationToken = default);
        Task<Wallet> GetOrCreateWalletByUserIdAsync(int userId, CancellationToken cancellationToken = default);
        Task UpdateWalletAsync(Wallet wallet, CancellationToken cancellationToken = default);
        Task AddTransactionAsync(WalletTransaction transaction, CancellationToken cancellationToken = default);
        Task<(List<WalletTransaction> Items, int TotalCount)> GetTransactionsAsync(int walletId, int page, int pageSize, CancellationToken cancellationToken = default);
    }
}
