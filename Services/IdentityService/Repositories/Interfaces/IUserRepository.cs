using System.Collections.Generic;
using System.Threading.Tasks;
using IdentityService.Models;

namespace IdentityService.Repositories.Interfaces
{
    public interface IUserRepository
    {
        Task<User?> GetByIdAsync(int userId);
        Task<User?> GetByEmailAsync(string email);
        Task<bool> ExistsByEmailAsync(string email);
        Task<Role?> GetRoleByNameAsync(string roleName);
        Task AddUserAsync(User user);
        Task AddUserRoleAsync(UserRole userRole);
        Task UpdateUserAsync(User user);
        Task SaveRefreshTokenAsync(RefreshToken refreshToken);
        Task<RefreshToken?> GetRefreshTokenAsync(string token);
        Task UpdateRefreshTokenAsync(RefreshToken refreshToken);
        Task<(List<User> Users, int TotalCount)> GetUsersPagedAsync(int page, int pageSize);
        Task<List<Role>> GetRolesByNamesAsync(List<string> roleNames);
        Task RemoveUserRolesAsync(int userId);
        Task SaveChangesAsync();
    }
}
