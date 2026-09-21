using System.Threading;
using System.Threading.Tasks;
using SystemService.DAL.Entities.Identity;

namespace SystemService.DAL.Repositories.Identity.Interfaces
{
    public interface IRoleRepository
    {
        Task<Role?> GetByIdAsync(int id, CancellationToken cancellationToken = default);
        Task<Role?> GetByNameAsync(string roleName, CancellationToken cancellationToken = default);
    }
}
