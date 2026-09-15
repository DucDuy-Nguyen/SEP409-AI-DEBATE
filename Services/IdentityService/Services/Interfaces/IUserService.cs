using System.Collections.Generic;
using System.Threading.Tasks;
using IdentityService.DTOs.Users;

namespace IdentityService.Services.Interfaces
{
    public interface IUserService
    {
        Task<UserResponse> GetUserProfileAsync(int userId);
        Task<UserResponse> UpdateUserProfileAsync(int userId, UpdateProfileRequest request);
        Task<(List<UserResponse> Users, int TotalCount)> GetUsersPagedAsync(int page, int pageSize);
        Task<UserResponse> GetUserByIdAsync(int userId);
        Task<UserResponse> UpdateUserStatusAsync(int userId, UpdateUserStatusRequest request);
        Task<UserResponse> UpdateUserRolesAsync(int userId, UpdateUserRoleRequest request);
    }
}
