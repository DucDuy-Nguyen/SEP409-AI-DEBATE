using Microsoft.EntityFrameworkCore;
using System.Threading;
using System.Threading.Tasks;
using SystemService.DAL.Context;
using SystemService.DAL.Entities.Identity;
using SystemService.DAL.Repositories.Identity.Interfaces;

namespace SystemService.DAL.Repositories.Identity.Implementations
{
    public class UserRepository : IUserRepository
    {
        private readonly SystemDbContext _context;

        public UserRepository(SystemDbContext context)
        {
            _context = context;
        }

        public async Task<User?> GetByIdAsync(int id, CancellationToken cancellationToken = default)
        {
            return await _context.Users
                .FirstOrDefaultAsync(u => u.UserId == id, cancellationToken);
        }

        public async Task<User?> GetByEmailAsync(string email, CancellationToken cancellationToken = default)
        {
            return await _context.Users
                .FirstOrDefaultAsync(u => u.Email == email, cancellationToken);
        }

        public async Task<User?> GetUserWithRolesAsync(int userId, CancellationToken cancellationToken = default)
        {
            return await _context.Users
                .Include(u => u.UserRoles)
                .ThenInclude(ur => ur.Role)
                .FirstOrDefaultAsync(u => u.UserId == userId, cancellationToken);
        }

        public async Task<bool> EmailExistsAsync(string email, CancellationToken cancellationToken = default)
        {
            return await _context.Users
                .AnyAsync(u => u.Email == email, cancellationToken);
        }

        public async Task AddAsync(User user, CancellationToken cancellationToken = default)
        {
            await _context.Users.AddAsync(user, cancellationToken);
            await _context.SaveChangesAsync(cancellationToken);
        }

        public async Task UpdateAsync(User user, CancellationToken cancellationToken = default)
        {
            _context.Users.Update(user);
            await _context.SaveChangesAsync(cancellationToken);
        }

        public async Task<(List<User> Items, int TotalCount)> GetPagedUsersAsync(
            string? searchTerm, int pageNumber, int pageSize, CancellationToken cancellationToken = default)
        {
            var query = _context.Users
                .Include(u => u.UserRoles)
                .ThenInclude(ur => ur.Role)
                .AsNoTracking()
                .AsQueryable();

            if (!string.IsNullOrWhiteSpace(searchTerm))
            {
                var term = searchTerm.Trim().ToLower();
                query = query.Where(u => u.FullName.ToLower().Contains(term) || u.Email.ToLower().Contains(term));
            }

            var totalCount = await query.CountAsync(cancellationToken);

            var items = await query
                .OrderByDescending(u => u.CreatedAt)
                .Skip((pageNumber - 1) * pageSize)
                .Take(pageSize)
                .ToListAsync(cancellationToken);

            return (items, totalCount);
        }

        public async Task<int> GetTotalUsersCountAsync(CancellationToken cancellationToken = default)
        {
            return await _context.Users.CountAsync(cancellationToken);
        }

        public async Task<int> CountUsersInRoleAsync(string roleName, CancellationToken cancellationToken = default)
        {
            return await _context.UserRoles
                .CountAsync(ur => ur.Role.RoleName == roleName && ur.User.IsActive, cancellationToken);
        }

        public async Task UpdateUserRolesAsync(int userId, IEnumerable<int> roleIds, CancellationToken cancellationToken = default)
        {
            var existingUserRoles = await _context.UserRoles
                .Where(ur => ur.UserId == userId)
                .ToListAsync(cancellationToken);

            _context.UserRoles.RemoveRange(existingUserRoles);

            foreach (var roleId in roleIds.Distinct())
            {
                await _context.UserRoles.AddAsync(new UserRole
                {
                    UserId = userId,
                    RoleId = roleId
                }, cancellationToken);
            }

            await _context.SaveChangesAsync(cancellationToken);
        }
    }
}
