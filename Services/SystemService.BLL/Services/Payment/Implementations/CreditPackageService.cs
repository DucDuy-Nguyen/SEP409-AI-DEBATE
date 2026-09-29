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
    public class CreditPackageService : ICreditPackageService
    {
        private readonly ICreditPackageRepository _packageRepository;

        public CreditPackageService(ICreditPackageRepository packageRepository)
        {
            _packageRepository = packageRepository;
        }

        public async Task<ApiResponse<List<CreditPackageResponse>>> GetActivePackagesAsync(CancellationToken cancellationToken = default)
        {
            var packages = await _packageRepository.GetActivePackagesAsync(cancellationToken);

            var result = packages.Select(p => new CreditPackageResponse
            {
                PackageId = p.PackageId,
                PackageCode = p.PackageCode,
                PackageName = p.PackageName,
                Price = p.Price,
                Currency = p.Currency,
                CreditAmount = p.CreditAmount,
                BonusCredit = p.BonusCredit
            }).ToList();

            return ApiResponse<List<CreditPackageResponse>>.SuccessResponse(result);
        }
    }
}
