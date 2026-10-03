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
        Task<List<CreditPackage>> GetAllAsync(CancellationToken cancellationToken = default);
        Task<CreditPackage?> GetByIdAsync(int packageId, CancellationToken cancellationToken = default);
        Task<bool> ExistsByPackageCodeAsync(string packageCode, int? excludePackageId = null, CancellationToken cancellationToken = default);
        Task<CreditPackage> CreateAsync(CreditPackage package, CancellationToken cancellationToken = default);
        Task UpdateAsync(CreditPackage package, CancellationToken cancellationToken = default);
    }
}

