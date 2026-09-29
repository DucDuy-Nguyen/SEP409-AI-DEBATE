using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using SystemService.DAL.Entities.Payment;

namespace SystemService.DAL.Repositories.Payment.Interfaces
{
    public interface ICreditPackageRepository
    {
        Task<List<CreditPackage>> GetActivePackagesAsync(CancellationToken cancellationToken = default);
        Task<CreditPackage?> GetActiveByIdAsync(int packageId, CancellationToken cancellationToken = default);
    }
}
