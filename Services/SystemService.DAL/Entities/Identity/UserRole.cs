using System;

namespace SystemService.DAL.Entities.Identity
{
    public class UserRole
    {
        public int UserId { get; set; }
        public int RoleId { get; set; }
        public DateTime AssignedAt { get; set; } = DateTime.UtcNow;

        public User User { get; set; } = null!;
        public Role Role { get; set; } = null!;
    }
}
