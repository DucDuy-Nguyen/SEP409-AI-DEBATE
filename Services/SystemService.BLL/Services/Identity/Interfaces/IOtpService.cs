using System.Threading;
using System.Threading.Tasks;
using SystemService.BLL.Common.Responses;

namespace SystemService.BLL.Services.Identity.Interfaces
{
    public interface IOtpService
    {
        Task<ApiResponse<object>> SendOtpAsync(string email, string type, CancellationToken cancellationToken = default);
        Task<ApiResponse<object>> VerifyOtpAsync(string email, string code, string type, CancellationToken cancellationToken = default);
        Task<bool> ValidateAndConsumeOtpAsync(string email, string code, string type, CancellationToken cancellationToken = default);
    }
}
