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
    }
}
