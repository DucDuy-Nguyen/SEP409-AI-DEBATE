using Microsoft.EntityFrameworkCore;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using SystemService.DAL.Context;
using SystemService.DAL.Entities.Competition;
using SystemService.DAL.Repositories.Competition.Interfaces;

namespace SystemService.DAL.Repositories.Competition.Implementations
{
    public class CompetitionRepository : ICompetitionRepository
    {
        private readonly SystemDbContext _context;

        public CompetitionRepository(SystemDbContext context)
        {
            _context = context;
        }

        public async Task<Entities.Competition.Competition?> GetByIdAsync(int id, CancellationToken cancellationToken = default)
        {
            return await _context.Competitions
                .FirstOrDefaultAsync(c => c.CompetitionId == id, cancellationToken);
        }

        public async Task<Entities.Competition.Competition?> GetDetailByIdAsync(int id, CancellationToken cancellationToken = default)
        {
            return await _context.Competitions
                .Include(c => c.Creator)
                .FirstOrDefaultAsync(c => c.CompetitionId == id, cancellationToken);
        }

        public async Task<List<Entities.Competition.Competition>> GetListAsync(string? status, string? type, bool? isPublic, string? keyword, CancellationToken cancellationToken = default)
        {
            var query = _context.Competitions.AsNoTracking().AsQueryable();

            if (!string.IsNullOrWhiteSpace(status))
            {
                query = query.Where(c => c.Status == status);
            }

            if (!string.IsNullOrWhiteSpace(type))
            {
                query = query.Where(c => c.CompetitionType == type);
            }

            if (isPublic.HasValue)
            {
                query = query.Where(c => c.IsPublic == isPublic.Value);
            }

            if (!string.IsNullOrWhiteSpace(keyword))
            {
                query = query.Where(c => c.Title.Contains(keyword) || (c.Description != null && c.Description.Contains(keyword)));
            }

            return await query.OrderByDescending(c => c.CreatedAt).ToListAsync(cancellationToken);
        }

        public async Task AddAsync(Entities.Competition.Competition competition, CancellationToken cancellationToken = default)
        {
            await _context.Competitions.AddAsync(competition, cancellationToken);
            await _context.SaveChangesAsync(cancellationToken);
        }

        public async Task CreateWithJudgeAsync(Entities.Competition.Competition competition, CompetitionJudge judge, CancellationToken cancellationToken = default)
        {
            using var transaction = await _context.Database.BeginTransactionAsync(cancellationToken);
            try
            {
                await _context.Competitions.AddAsync(competition, cancellationToken);
                await _context.SaveChangesAsync(cancellationToken);

                judge.CompetitionId = competition.CompetitionId;
                await _context.CompetitionJudges.AddAsync(judge, cancellationToken);
                await _context.SaveChangesAsync(cancellationToken);

                await transaction.CommitAsync(cancellationToken);
            }
            catch
            {
                await transaction.RollbackAsync(cancellationToken);
                throw;
            }
        }

        public async Task UpdateAsync(Entities.Competition.Competition competition, CancellationToken cancellationToken = default)
        {
            _context.Competitions.Update(competition);
            await _context.SaveChangesAsync(cancellationToken);
        }

        public async Task<bool> ExistsAsync(int id, CancellationToken cancellationToken = default)
        {
            return await _context.Competitions.AnyAsync(c => c.CompetitionId == id, cancellationToken);
        }

        public async Task<List<CompetitionRound>> GetRoundsWithMatchesAsync(int competitionId, CancellationToken cancellationToken = default)
        {
            return await _context.CompetitionRounds.AsNoTracking()
                .Where(r => r.CompetitionId == competitionId)
                .Include(r => r.Matches).ThenInclude(m => m.Participants)
                .OrderBy(r => r.RoundNumber)
                .ToListAsync(cancellationToken);
        }

        public async Task<bool> StartWithReadyMatchesAsync(int competitionId, CancellationToken cancellationToken = default)
        {
            await using var transaction = await _context.Database.BeginTransactionAsync(System.Data.IsolationLevel.Serializable, cancellationToken);
            var changed = await _context.Competitions
                .Where(c => c.CompetitionId == competitionId && c.Status == "RegistrationClosed")
                .ExecuteUpdateAsync(s => s.SetProperty(c => c.Status, "Ongoing")
                    .SetProperty(c => c.UpdatedAt, DateTime.UtcNow), cancellationToken);
            if (changed != 1) return false;

            await _context.CompetitionMatches
                .Where(m => m.CompetitionId == competitionId && m.Status == "Scheduled" && m.Participants.Count == 2)
                .ExecuteUpdateAsync(s => s.SetProperty(m => m.Status, "Ready")
                    .SetProperty(m => m.UpdatedAt, DateTime.UtcNow), cancellationToken);
            await _context.CompetitionRounds
                .Where(r => r.CompetitionId == competitionId && r.Status == "Pending"
                    && r.Matches.Any(m => m.Status == "Ready"))
                .ExecuteUpdateAsync(s => s.SetProperty(r => r.Status, "Ongoing"), cancellationToken);
            await transaction.CommitAsync(cancellationToken);
            return true;
        }
    }
}
