using Microsoft.EntityFrameworkCore;
using System.Threading;
using System.Threading.Tasks;
using SystemService.Data;
using SystemService.Models.Entities.Identity;
using SystemService.Repositories.Identity.Interfaces;

namespace SystemService.Repositories.Identity.Implementations
{
    public class RoleRepository : IRoleRepository
    {
        private readonly SystemDbContext _context;

        public RoleRepository(SystemDbContext context)
        {
            _context = context;
        }

        public async Task<Role?> GetByIdAsync(int id, CancellationToken cancellationToken = default)
        {
            return await _context.Roles
                .FirstOrDefaultAsync(r => r.RoleId == id, cancellationToken);
        }

        public async Task<Role?> GetByNameAsync(string roleName, CancellationToken cancellationToken = default)
        {
            return await _context.Roles
                .FirstOrDefaultAsync(r => r.RoleName == roleName, cancellationToken);
        }
    }
}
