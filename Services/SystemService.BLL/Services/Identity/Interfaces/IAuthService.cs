using System.Threading;
using System.Threading.Tasks;
using SystemService.BLL.Common.Responses;
using SystemService.BLL.DTOs.Identity.Auth;

namespace SystemService.BLL.Services.Identity.Interfaces
{
    public interface IAuthService
    {
        Task<ApiResponse<object>> RegisterAsync(RegisterRequest request, CancellationToken cancellationToken = default);
        Task<ApiResponse<LoginResponse>> LoginAsync(LoginRequest request, CancellationToken cancellationToken = default);
        Task<ApiResponse<LoginResponse>> GoogleLoginAsync(GoogleLoginRequest request, CancellationToken cancellationToken = default);
        Task<ApiResponse<object>> SendOtpAsync(SendOtpRequest request, CancellationToken cancellationToken = default);
        Task<ApiResponse<object>> VerifyOtpAsync(VerifyOtpRequest request, CancellationToken cancellationToken = default);
        Task<ApiResponse<object>> ResetPasswordAsync(ResetPasswordRequest request, CancellationToken cancellationToken = default);
        Task<ApiResponse<object>> ChangePasswordAsync(int userId, ChangePasswordRequest request, CancellationToken cancellationToken = default);
    }
}
