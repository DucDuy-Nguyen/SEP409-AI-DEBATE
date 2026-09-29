using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.EntityFrameworkCore;
using SystemService.DAL.Context;
using SystemService.DAL.Entities.Payment;
using SystemService.DAL.Repositories.Payment.Interfaces;

namespace SystemService.DAL.Repositories.Payment.Implementations
{
    public class CreditPackageRepository : ICreditPackageRepository
    {
        private readonly SystemDbContext _context;

        public CreditPackageRepository(SystemDbContext context)
        {
            _context = context;
        }

        public async Task<List<CreditPackage>> GetActivePackagesAsync(CancellationToken cancellationToken = default)
        {
            return await _context.CreditPackages
                .Where(cp => cp.IsActive)
                .OrderBy(cp => cp.Price)
                .ToListAsync(cancellationToken);
        }

        public async Task<CreditPackage?> GetActiveByIdAsync(int packageId, CancellationToken cancellationToken = default)
        {
            return await _context.CreditPackages
                .FirstOrDefaultAsync(cp => cp.PackageId == packageId && cp.IsActive, cancellationToken);
        }
    }
}
