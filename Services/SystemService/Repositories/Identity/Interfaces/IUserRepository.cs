using System.Threading;
using System.Threading.Tasks;
using SystemService.Models.Entities.Identity;

namespace SystemService.Repositories.Identity.Interfaces
{
    public interface IUserRepository
    {
        Task<User?> GetByIdAsync(int id, CancellationToken cancellationToken = default);
        Task<User?> GetByEmailAsync(string email, CancellationToken cancellationToken = default);
        Task<User?> GetUserWithRolesAsync(int userId, CancellationToken cancellationToken = default);
        Task<bool> EmailExistsAsync(string email, CancellationToken cancellationToken = default);
        Task AddAsync(User user, CancellationToken cancellationToken = default);
        Task UpdateAsync(User user, CancellationToken cancellationToken = default);
    }
}
