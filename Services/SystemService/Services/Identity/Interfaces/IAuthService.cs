using System.Threading;
using System.Threading.Tasks;
using SystemService.Common.Responses;
using SystemService.Models.DTOs.Identity.Auth;

namespace SystemService.Services.Identity.Interfaces
{
    public interface IAuthService
    {
        Task<ApiResponse<object>> RegisterAsync(RegisterRequest request, CancellationToken cancellationToken = default);
        Task<ApiResponse<LoginResponse>> LoginAsync(LoginRequest request, CancellationToken cancellationToken = default);
        Task<ApiResponse<object>> ChangePasswordAsync(int userId, ChangePasswordRequest request, CancellationToken cancellationToken = default);
    }
}
