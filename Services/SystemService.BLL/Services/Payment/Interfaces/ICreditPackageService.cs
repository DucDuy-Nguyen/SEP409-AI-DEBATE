using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using SystemService.BLL.Common.Responses;
using SystemService.BLL.DTOs.Payment;

namespace SystemService.BLL.Services.Payment.Interfaces
{
    public interface ICreditPackageService
    {
        Task<ApiResponse<List<CreditPackageResponse>>> GetActivePackagesAsync(CancellationToken cancellationToken = default);
        Task<ApiResponse<List<CreditPackageAdminResponse>>> GetAllPackagesAsync(CancellationToken cancellationToken = default);
        Task<ApiResponse<CreditPackageAdminResponse>> CreatePackageAsync(CreateCreditPackageRequest request, CancellationToken cancellationToken = default);
        Task<ApiResponse<CreditPackageAdminResponse>> PatchPackageAsync(int packageId, PatchCreditPackageRequest request, CancellationToken cancellationToken = default);
    }
}
