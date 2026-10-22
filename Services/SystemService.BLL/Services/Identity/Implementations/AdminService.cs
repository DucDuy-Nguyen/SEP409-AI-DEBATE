using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using SystemService.BLL.Common.Responses;
using SystemService.BLL.DTOs.Identity.Admin;
using SystemService.BLL.Services.Identity.Interfaces;
using SystemService.DAL.Repositories.Debate.Interfaces;
using SystemService.DAL.Repositories.Identity.Interfaces;

namespace SystemService.BLL.Services.Identity.Implementations
{
    public class AdminService : IAdminService
    {
        private readonly IUserRepository _userRepository;
        private readonly IRoleRepository _roleRepository;
        private readonly IDebateRepository _debateRepository;
        private readonly ITopicRepository _topicRepository;

        public AdminService(
            IUserRepository userRepository,
            IRoleRepository roleRepository,
            IDebateRepository debateRepository,
            ITopicRepository topicRepository)
        {
            _userRepository = userRepository;
            _roleRepository = roleRepository;
            _debateRepository = debateRepository;
            _topicRepository = topicRepository;
        }

        public async Task<ApiResponse<PagedResult<AdminUserListItemDto>>> GetUsersAsync(
            string? searchTerm, int pageNumber, int pageSize, CancellationToken cancellationToken = default)
        {
            var page = pageNumber < 1 ? 1 : pageNumber;
            var size = pageSize < 1 ? 10 : (pageSize > 100 ? 100 : pageSize);

            var (users, totalCount) = await _userRepository.GetPagedUsersAsync(searchTerm, page, size, cancellationToken);

            var userDtos = users.Select(u => new AdminUserListItemDto
            {
                UserId = u.UserId,
                FullName = u.FullName,
                Email = u.Email,
                PhoneNumber = u.PhoneNumber,
                AvatarUrl = u.AvatarUrl,
                IsEmailVerified = u.IsEmailVerified,
                IsActive = u.IsActive,
                CreatedAt = u.CreatedAt,
                Roles = u.UserRoles.Select(ur => ur.Role.RoleName).ToList()
            }).ToList();

            var result = new PagedResult<AdminUserListItemDto>
            {
                Items = userDtos,
                TotalCount = totalCount,
                PageNumber = page,
                PageSize = size
            };

            return ApiResponse<PagedResult<AdminUserListItemDto>>.SuccessResponse(result, "Users retrieved successfully.");
        }

        public async Task<ApiResponse<AdminUserListItemDto>> GetUserByIdAsync(
            int userId, CancellationToken cancellationToken = default)
        {
            var user = await _userRepository.GetUserWithRolesAsync(userId, cancellationToken);
            if (user == null)
            {
                return ApiResponse<AdminUserListItemDto>.FailureResponse("User not found.");
            }

            var dto = new AdminUserListItemDto
            {
                UserId = user.UserId,
                FullName = user.FullName,
                Email = user.Email,
                PhoneNumber = user.PhoneNumber,
                AvatarUrl = user.AvatarUrl,
                IsEmailVerified = user.IsEmailVerified,
                IsActive = user.IsActive,
                CreatedAt = user.CreatedAt,
                Roles = user.UserRoles.Select(ur => ur.Role.RoleName).ToList()
            };

            return ApiResponse<AdminUserListItemDto>.SuccessResponse(dto);
        }

        public async Task<ApiResponse<object>> UpdateUserStatusAsync(
            int currentAdminId, int targetUserId, UpdateUserStatusRequest request, CancellationToken cancellationToken = default)
        {
            // Business Rule: Admin cannot deactivate their own account
            if (currentAdminId == targetUserId && !request.IsActive)
            {
                return ApiResponse<object>.FailureResponse("You cannot deactivate your own admin account.");
            }

            var user = await _userRepository.GetByIdAsync(targetUserId, cancellationToken);
            if (user == null)
            {
                return ApiResponse<object>.FailureResponse("User not found.");
            }

            user.IsActive = request.IsActive;
            user.UpdatedAt = DateTime.UtcNow;

            await _userRepository.UpdateAsync(user, cancellationToken);

            var message = request.IsActive ? "User account activated successfully." : "User account deactivated successfully.";
            return ApiResponse<object>.SuccessResponse(new { }, message);
        }

        public async Task<ApiResponse<List<RoleDto>>> GetRolesAsync(CancellationToken cancellationToken = default)
        {
            var roles = await _roleRepository.GetAllRolesAsync(cancellationToken);
            var dtos = roles.Select(r => new RoleDto
            {
                RoleId = r.RoleId,
                RoleName = r.RoleName,
                Description = r.Description
            }).ToList();

            return ApiResponse<List<RoleDto>>.SuccessResponse(dtos);
        }

        public async Task<ApiResponse<object>> AssignUserRolesAsync(
            int currentAdminId, int targetUserId, AssignRolesRequest request, CancellationToken cancellationToken = default)
        {
            var user = await _userRepository.GetUserWithRolesAsync(targetUserId, cancellationToken);
            if (user == null)
            {
                return ApiResponse<object>.FailureResponse("User not found.");
            }

            var allRoles = await _roleRepository.GetAllRolesAsync(cancellationToken);
            var validRoleIds = allRoles.Select(r => r.RoleId).ToHashSet();
            var adminRole = allRoles.FirstOrDefault(r => r.RoleName.Equals("Admin", StringComparison.OrdinalIgnoreCase));

            // Validate that provided role IDs exist
            if (request.RoleIds.Any(id => !validRoleIds.Contains(id)))
            {
                return ApiResponse<object>.FailureResponse("One or more invalid Role IDs provided.");
            }

            // Business Rule: Admin cannot revoke their own Admin role if they are the last active Admin
            if (adminRole != null)
            {
                bool userCurrentlyHasAdmin = user.UserRoles.Any(ur => ur.RoleId == adminRole.RoleId);
                bool willHaveAdmin = request.RoleIds.Contains(adminRole.RoleId);

                if (userCurrentlyHasAdmin && !willHaveAdmin)
                {
                    int totalActiveAdmins = await _userRepository.CountUsersInRoleAsync("Admin", cancellationToken);
                    if (totalActiveAdmins <= 1)
                    {
                        return ApiResponse<object>.FailureResponse("Cannot remove Admin role. The system must have at least one active Admin.");
                    }
                }
            }

            await _userRepository.UpdateUserRolesAsync(targetUserId, request.RoleIds, cancellationToken);

            return ApiResponse<object>.SuccessResponse(new { }, "User roles updated successfully.");
        }

        public async Task<ApiResponse<DashboardStatsResponse>> GetDashboardStatsAsync(CancellationToken cancellationToken = default)
        {
            var totalUsersTask = _userRepository.GetTotalUsersCountAsync(cancellationToken);
            var totalSessionsTask = _debateRepository.GetTotalDebateSessionsCountAsync(cancellationToken);
            var totalTopicsTask = _topicRepository.GetTotalTopicsCountAsync(cancellationToken);

            await Task.WhenAll(totalUsersTask, totalSessionsTask, totalTopicsTask);

            var stats = new DashboardStatsResponse
            {
                TotalUsers = await totalUsersTask,
                TotalDebateSessions = await totalSessionsTask,
                TotalTopics = await totalTopicsTask
            };

            return ApiResponse<DashboardStatsResponse>.SuccessResponse(stats, "Dashboard statistics retrieved successfully.");
        }
    }
}
