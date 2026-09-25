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
    public class CompetitionJudgeRepository : ICompetitionJudgeRepository
    {
        private readonly SystemDbContext _context;

        public CompetitionJudgeRepository(SystemDbContext context)
        {
            _context = context;
        }

        public async Task<List<CompetitionJudge>> GetListByCompetitionAsync(int competitionId, CancellationToken cancellationToken = default)
        {
            return await _context.CompetitionJudges
                .Include(j => j.User)
                .Where(j => j.CompetitionId == competitionId)
                .OrderBy(j => j.AssignedAt)
                .ToListAsync(cancellationToken);
        }

        public async Task AddAsync(CompetitionJudge judge, CancellationToken cancellationToken = default)
        {
            await _context.CompetitionJudges.AddAsync(judge, cancellationToken);
            await _context.SaveChangesAsync(cancellationToken);
        }
    }
}
