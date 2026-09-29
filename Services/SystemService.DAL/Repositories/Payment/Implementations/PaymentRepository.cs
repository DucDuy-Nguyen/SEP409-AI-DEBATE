using System.Threading;
using System.Threading.Tasks;
using Microsoft.EntityFrameworkCore;
using SystemService.DAL.Context;
using SystemService.DAL.Entities.Payment;
using SystemService.DAL.Repositories.Payment.Interfaces;

namespace SystemService.DAL.Repositories.Payment.Implementations
{
    public class PaymentRepository : IPaymentRepository
    {
        private readonly SystemDbContext _context;

        public PaymentRepository(SystemDbContext context)
        {
            _context = context;
        }

        public async Task<PaymentTransaction> CreateAsync(PaymentTransaction payment, CancellationToken cancellationToken = default)
        {
            await _context.PaymentTransactions.AddAsync(payment, cancellationToken);
            await _context.SaveChangesAsync(cancellationToken);
            return payment;
        }

        public async Task<PaymentTransaction?> GetByIdAsync(long paymentId, CancellationToken cancellationToken = default)
        {
            return await _context.PaymentTransactions
                .Include(pt => pt.Package)
                .FirstOrDefaultAsync(pt => pt.PaymentId == paymentId, cancellationToken);
        }

        public async Task<PaymentTransaction?> GetByProviderOrderCodeAsync(string provider, long providerOrderCode, CancellationToken cancellationToken = default)
        {
            return await _context.PaymentTransactions
                .Include(pt => pt.Package)
                .FirstOrDefaultAsync(pt => pt.Provider == provider && pt.ProviderOrderCode == providerOrderCode, cancellationToken);
        }

        public async Task<PaymentTransaction?> GetByProviderOrderCodeForUpdateAsync(string provider, long providerOrderCode, CancellationToken cancellationToken = default)
        {
            return await _context.PaymentTransactions
                .FromSqlInterpolated($"SELECT * FROM PaymentTransactions WITH (UPDLOCK, ROWLOCK) WHERE Provider = {provider} AND ProviderOrderCode = {providerOrderCode}")
                .FirstOrDefaultAsync(cancellationToken);
        }

        public async Task UpdateAsync(PaymentTransaction payment, CancellationToken cancellationToken = default)
        {
            _context.PaymentTransactions.Update(payment);
            await _context.SaveChangesAsync(cancellationToken);
        }
    }
}
