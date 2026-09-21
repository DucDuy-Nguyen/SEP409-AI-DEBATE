using System.Threading;
using System.Threading.Tasks;
using SystemService.Common.Responses;
using SystemService.Models.DTOs.Identity.Users;

namespace SystemService.Services.Identity.Interfaces
{
    public interface IUserService
    {
        Task<ApiResponse<UserProfileResponse>> GetMyProfileAsync(int userId, CancellationToken cancellationToken = default);
        Task<ApiResponse<UserProfileResponse>> UpdateMyProfileAsync(int userId, UpdateProfileRequest request, CancellationToken cancellationToken = default);
    }
}
