using System;
using System.Collections.Generic;

namespace SystemService.BLL.DTOs.Identity.Admin
{
    public class AdminUserListItemDto
    {
        public int UserId { get; set; }
        public string FullName { get; set; } = null!;
        public string Email { get; set; } = null!;
        public string? PhoneNumber { get; set; }
        public string? AvatarUrl { get; set; }
        public bool IsEmailVerified { get; set; }
        public bool IsActive { get; set; }
        public DateTime CreatedAt { get; set; }
        public List<string> Roles { get; set; } = new List<string>();
    }

    public class UpdateUserStatusRequest
    {
        public bool IsActive { get; set; }
    }

    public class RoleDto
    {
        public int RoleId { get; set; }
        public string RoleName { get; set; } = null!;
        public string? Description { get; set; }
    }

    public class AssignRolesRequest
    {
        public List<int> RoleIds { get; set; } = new List<int>();
    }

    public class DashboardStatsResponse
    {
        public int TotalUsers { get; set; }
        public int TotalDebateSessions { get; set; }
        public int TotalTopics { get; set; }
    }
}
