using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using SystemService.BLL.Common.Responses;
using SystemService.BLL.DTOs.Identity.Admin;

namespace SystemService.BLL.Services.Identity.Interfaces
{
    public interface IAdminService
    {
        Task<ApiResponse<PagedResult<AdminUserListItemDto>>> GetUsersAsync(
            string? searchTerm, int pageNumber, int pageSize, CancellationToken cancellationToken = default);

        Task<ApiResponse<AdminUserListItemDto>> GetUserByIdAsync(
            int userId, CancellationToken cancellationToken = default);

        Task<ApiResponse<object>> UpdateUserStatusAsync(
            int currentAdminId, int targetUserId, UpdateUserStatusRequest request, CancellationToken cancellationToken = default);

        Task<ApiResponse<List<RoleDto>>> GetRolesAsync(
            CancellationToken cancellationToken = default);

        Task<ApiResponse<object>> AssignUserRolesAsync(
            int currentAdminId, int targetUserId, AssignRolesRequest request, CancellationToken cancellationToken = default);

        Task<ApiResponse<DashboardStatsResponse>> GetDashboardStatsAsync(
            CancellationToken cancellationToken = default);
    }
}
