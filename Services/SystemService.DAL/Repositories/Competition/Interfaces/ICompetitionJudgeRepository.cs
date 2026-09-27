using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using SystemService.DAL.Entities.Competition;

namespace SystemService.DAL.Repositories.Competition.Interfaces
{
    public interface ICompetitionJudgeRepository
    {
        Task<List<CompetitionJudge>> GetListByCompetitionAsync(int competitionId, CancellationToken cancellationToken = default);
        Task AddAsync(CompetitionJudge judge, CancellationToken cancellationToken = default);
    }
}
