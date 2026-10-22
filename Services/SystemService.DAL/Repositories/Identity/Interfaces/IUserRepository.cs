using System.Threading;
using System.Threading.Tasks;
using SystemService.DAL.Entities.Identity;

namespace SystemService.DAL.Repositories.Identity.Interfaces
{
    public interface IUserRepository
    {
        Task<User?> GetByIdAsync(int id, CancellationToken cancellationToken = default);
        Task<User?> GetByEmailAsync(string email, CancellationToken cancellationToken = default);
        Task<User?> GetUserWithRolesAsync(int userId, CancellationToken cancellationToken = default);
        Task<bool> EmailExistsAsync(string email, CancellationToken cancellationToken = default);
        Task AddAsync(User user, CancellationToken cancellationToken = default);
        Task UpdateAsync(User user, CancellationToken cancellationToken = default);
        Task<(List<User> Items, int TotalCount)> GetPagedUsersAsync(string? searchTerm, int pageNumber, int pageSize, CancellationToken cancellationToken = default);
        Task<int> GetTotalUsersCountAsync(CancellationToken cancellationToken = default);
        Task<int> CountUsersInRoleAsync(string roleName, CancellationToken cancellationToken = default);
        Task UpdateUserRolesAsync(int userId, IEnumerable<int> roleIds, CancellationToken cancellationToken = default);
    }
}
