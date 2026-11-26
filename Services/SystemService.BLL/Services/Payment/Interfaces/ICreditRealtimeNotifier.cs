using System.Threading;
using System.Threading.Tasks;

namespace SystemService.BLL.Services.Payment.Interfaces
{
    public interface ICreditRealtimeNotifier
    {
        Task NotifyCreditBalanceUpdatedAsync(
            int userId,
            long balance,
            long previousBalance,
            long amountChanged,
            long? transactionId = null,
            string? referenceId = null,
            string? reason = null,
            CancellationToken cancellationToken = default);

        Task NotifyCreditTransactionCreatedAsync(
            int userId,
            object transactionData,
            CancellationToken cancellationToken = default);
    }
}
