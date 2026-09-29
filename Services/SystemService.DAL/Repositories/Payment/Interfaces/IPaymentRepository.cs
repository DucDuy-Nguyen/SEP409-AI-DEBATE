using System.Threading;
using System.Threading.Tasks;
using SystemService.DAL.Entities.Payment;

namespace SystemService.DAL.Repositories.Payment.Interfaces
{
    public interface IPaymentRepository
    {
        Task<PaymentTransaction> CreateAsync(PaymentTransaction payment, CancellationToken cancellationToken = default);
        Task<PaymentTransaction?> GetByIdAsync(long paymentId, CancellationToken cancellationToken = default);
        Task<PaymentTransaction?> GetByProviderOrderCodeAsync(string provider, long providerOrderCode, CancellationToken cancellationToken = default);
        Task<PaymentTransaction?> GetByProviderOrderCodeForUpdateAsync(string provider, long providerOrderCode, CancellationToken cancellationToken = default);
        Task UpdateAsync(PaymentTransaction payment, CancellationToken cancellationToken = default);
    }
}
