using System;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using SystemService.BLL.Common.Responses;
using SystemService.BLL.DTOs.Identity.Users;
using SystemService.BLL.Services.Identity.Interfaces;
using SystemService.DAL.Repositories.Identity.Interfaces;

namespace SystemService.BLL.Services.Identity.Implementations
{
    public class UserService : IUserService
    {
        private readonly IUserRepository _userRepository;

        public UserService(IUserRepository userRepository)
        {
            _userRepository = userRepository;
        }

        public async Task<ApiResponse<UserProfileResponse>> GetMyProfileAsync(int userId, CancellationToken cancellationToken = default)
        {
            var user = await _userRepository.GetUserWithRolesAsync(userId, cancellationToken);
            if (user == null)
            {
                return ApiResponse<UserProfileResponse>.FailureResponse("User not found.");
            }

            var roles = user.UserRoles.Select(ur => ur.Role.RoleName).ToList();

            var response = new UserProfileResponse
            {
                UserId = user.UserId,
                FullName = user.FullName,
                Email = user.Email,
                AvatarUrl = user.AvatarUrl,
                DateOfBirth = user.DateOfBirth,
                Gender = user.Gender,
                PhoneNumber = user.PhoneNumber,
                IsEmailVerified = user.IsEmailVerified,
                IsActive = user.IsActive,
                CreatedAt = user.CreatedAt,
                UpdatedAt = user.UpdatedAt,
                Roles = roles
            };

            return ApiResponse<UserProfileResponse>.SuccessResponse(response, "User profile retrieved successfully.");
        }

        public async Task<ApiResponse<UserProfileResponse>> UpdateMyProfileAsync(int userId, UpdateProfileRequest request, CancellationToken cancellationToken = default)
        {
            var user = await _userRepository.GetUserWithRolesAsync(userId, cancellationToken);
            if (user == null)
            {
                return ApiResponse<UserProfileResponse>.FailureResponse("User not found.");
            }

            user.FullName = request.FullName.Trim();
            user.AvatarUrl = request.AvatarUrl;
            user.DateOfBirth = request.DateOfBirth;
            user.Gender = request.Gender;
            user.PhoneNumber = request.PhoneNumber;
            user.UpdatedAt = DateTime.UtcNow;

            await _userRepository.UpdateAsync(user, cancellationToken);

            var roles = user.UserRoles.Select(ur => ur.Role.RoleName).ToList();

            var response = new UserProfileResponse
            {
                UserId = user.UserId,
                FullName = user.FullName,
                Email = user.Email,
                AvatarUrl = user.AvatarUrl,
                DateOfBirth = user.DateOfBirth,
                Gender = user.Gender,
                PhoneNumber = user.PhoneNumber,
                IsEmailVerified = user.IsEmailVerified,
                IsActive = user.IsActive,
                CreatedAt = user.CreatedAt,
                UpdatedAt = user.UpdatedAt,
                Roles = roles
            };

            return ApiResponse<UserProfileResponse>.SuccessResponse(response, "User profile updated successfully.");
        }
    }
}
