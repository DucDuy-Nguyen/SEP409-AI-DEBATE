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
    public class CompetitionTeamRepository : ICompetitionTeamRepository
    {
        private readonly SystemDbContext _context;

        public CompetitionTeamRepository(SystemDbContext context)
        {
            _context = context;
        }

        public async Task<CompetitionTeam?> GetByIdAsync(int teamId, CancellationToken cancellationToken = default)
        {
            return await _context.CompetitionTeams
                .Include(t => t.Captain)
                .FirstOrDefaultAsync(t => t.TeamId == teamId, cancellationToken);
        }

        public async Task<CompetitionTeam?> GetWithMembersAsync(int teamId, CancellationToken cancellationToken = default)
        {
            return await _context.CompetitionTeams
                .Include(t => t.Captain)
                .Include(t => t.TeamMembers)
                    .ThenInclude(tm => tm.User)
                .FirstOrDefaultAsync(t => t.TeamId == teamId, cancellationToken);
        }

        public async Task<List<CompetitionTeam>> GetListByCompetitionAsync(int competitionId, CancellationToken cancellationToken = default)
        {
            return await _context.CompetitionTeams
                .Include(t => t.Captain)
                .Where(t => t.CompetitionId == competitionId)
                .OrderByDescending(t => t.CreatedAt)
                .ToListAsync(cancellationToken);
        }

        public async Task<bool> IsTeamNameExistsAsync(int competitionId, string teamName, CancellationToken cancellationToken = default)
        {
            return await _context.CompetitionTeams
                .AnyAsync(t => t.CompetitionId == competitionId && t.TeamName == teamName, cancellationToken);
        }

        public async Task<bool> IsUserInTeamAsync(int teamId, int userId, CancellationToken cancellationToken = default)
        {
            return await _context.CompetitionTeamMembers
                .AnyAsync(tm => tm.TeamId == teamId && tm.UserId == userId, cancellationToken);
        }

        public async Task<CompetitionTeamMember?> GetTeamMemberAsync(int teamId, int userId, CancellationToken cancellationToken = default)
        {
            return await _context.CompetitionTeamMembers
                .FirstOrDefaultAsync(tm => tm.TeamId == teamId && tm.UserId == userId, cancellationToken);
        }

        public async Task AddTeamAsync(CompetitionTeam team, CancellationToken cancellationToken = default)
        {
            await _context.CompetitionTeams.AddAsync(team, cancellationToken);
            await _context.SaveChangesAsync(cancellationToken);
        }

        public async Task AddMemberAsync(CompetitionTeamMember member, CancellationToken cancellationToken = default)
        {
            await _context.CompetitionTeamMembers.AddAsync(member, cancellationToken);
            await _context.SaveChangesAsync(cancellationToken);
        }

        public async Task RemoveMemberAsync(CompetitionTeamMember member, CancellationToken cancellationToken = default)
        {
            _context.CompetitionTeamMembers.Remove(member);
            await _context.SaveChangesAsync(cancellationToken);
        }

        public async Task UpdateTeamAsync(CompetitionTeam team, CancellationToken cancellationToken = default)
        {
            _context.CompetitionTeams.Update(team);
            await _context.SaveChangesAsync(cancellationToken);
        }
    }
}
