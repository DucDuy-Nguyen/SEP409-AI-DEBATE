using Microsoft.EntityFrameworkCore;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using SystemService.DAL.Context;
using SystemService.DAL.Entities.Competition;
using SystemService.DAL.Repositories.Competition.Interfaces;

namespace SystemService.DAL.Repositories.Competition.Implementations
{
    public class CompetitionRegistrationRepository : ICompetitionRegistrationRepository
    {
        private readonly SystemDbContext _context;

        public CompetitionRegistrationRepository(SystemDbContext context)
        {
            _context = context;
        }

        public async Task<CompetitionRegistration?> GetByIdAsync(long id, CancellationToken cancellationToken = default)
        {
            return await _context.CompetitionRegistrations
                .Include(r => r.User)
                .Include(r => r.Reviewer)
                .FirstOrDefaultAsync(r => r.RegistrationId == id, cancellationToken);
        }

        public async Task<CompetitionRegistration?> GetByCompetitionAndUserAsync(int competitionId, int userId, CancellationToken cancellationToken = default)
        {
            return await _context.CompetitionRegistrations
                .Include(r => r.User)
                .FirstOrDefaultAsync(r => r.CompetitionId == competitionId && r.UserId == userId, cancellationToken);
        }

        public async Task<List<CompetitionRegistration>> GetListByCompetitionAsync(int competitionId, string? status, CancellationToken cancellationToken = default)
        {
            var query = _context.CompetitionRegistrations
                .Include(r => r.User)
                .Include(r => r.Reviewer)
                .Where(r => r.CompetitionId == competitionId);

            if (!string.IsNullOrWhiteSpace(status))
            {
                query = query.Where(r => r.Status == status);
            }

            return await query.OrderByDescending(r => r.RegisteredAt).ToListAsync(cancellationToken);
        }

        public async Task<bool> HasUserRegisteredAsync(int competitionId, int userId, CancellationToken cancellationToken = default)
        {
            return await _context.CompetitionRegistrations
                .AnyAsync(r => r.CompetitionId == competitionId && r.UserId == userId, cancellationToken);
        }

        public async Task AddAsync(CompetitionRegistration registration, CancellationToken cancellationToken = default)
        {
            await _context.CompetitionRegistrations.AddAsync(registration, cancellationToken);
            await _context.SaveChangesAsync(cancellationToken);
        }

        public async Task UpdateAsync(CompetitionRegistration registration, CancellationToken cancellationToken = default)
        {
            _context.CompetitionRegistrations.Update(registration);
            await _context.SaveChangesAsync(cancellationToken);
        }
    }
}
