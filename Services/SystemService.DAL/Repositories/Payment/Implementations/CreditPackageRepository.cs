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

        public async Task<List<CreditPackage>> GetAllAsync(CancellationToken cancellationToken = default)
        {
            return await _context.CreditPackages
                .OrderBy(cp => cp.PackageId)
                .ToListAsync(cancellationToken);
        }

        public async Task<CreditPackage?> GetByIdAsync(int packageId, CancellationToken cancellationToken = default)
        {
            return await _context.CreditPackages
                .FirstOrDefaultAsync(cp => cp.PackageId == packageId, cancellationToken);
        }

        public async Task<bool> ExistsByPackageCodeAsync(string packageCode, int? excludePackageId = null, CancellationToken cancellationToken = default)
        {
            var query = _context.CreditPackages.Where(cp => cp.PackageCode == packageCode);
            if (excludePackageId.HasValue)
            {
                query = query.Where(cp => cp.PackageId != excludePackageId.Value);
            }
            return await query.AnyAsync(cancellationToken);
        }

        public async Task<CreditPackage> CreateAsync(CreditPackage package, CancellationToken cancellationToken = default)
        {
            await _context.CreditPackages.AddAsync(package, cancellationToken);
            await _context.SaveChangesAsync(cancellationToken);
            return package;
        }

        public async Task UpdateAsync(CreditPackage package, CancellationToken cancellationToken = default)
        {
            _context.CreditPackages.Update(package);
            await _context.SaveChangesAsync(cancellationToken);
        }
    }
}
