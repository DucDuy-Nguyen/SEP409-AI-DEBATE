using System.Threading;
using System.Threading.Tasks;
using SystemService.Models.Entities.Identity;

namespace SystemService.Repositories.Identity.Interfaces
{
    public interface IRoleRepository
    {
        Task<Role?> GetByIdAsync(int id, CancellationToken cancellationToken = default);
        Task<Role?> GetByNameAsync(string roleName, CancellationToken cancellationToken = default);
    }
}
