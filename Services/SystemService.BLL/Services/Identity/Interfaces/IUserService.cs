using System.Threading;
using System.Threading.Tasks;
using SystemService.BLL.Common.Responses;
using SystemService.BLL.DTOs.Identity.Users;

namespace SystemService.BLL.Services.Identity.Interfaces
{
    public interface IUserService
    {
        Task<ApiResponse<UserProfileResponse>> GetMyProfileAsync(int userId, CancellationToken cancellationToken = default);
        Task<ApiResponse<UserProfileResponse>> UpdateMyProfileAsync(int userId, UpdateProfileRequest request, CancellationToken cancellationToken = default);
    }
}
