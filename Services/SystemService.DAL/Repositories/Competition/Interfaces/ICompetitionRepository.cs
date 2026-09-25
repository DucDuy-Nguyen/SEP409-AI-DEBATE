using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using SystemService.DAL.Entities.Competition;

namespace SystemService.DAL.Repositories.Competition.Interfaces
{
    public interface ICompetitionRepository
    {
        Task<Entities.Competition.Competition?> GetByIdAsync(int id, CancellationToken cancellationToken = default);
        Task<Entities.Competition.Competition?> GetDetailByIdAsync(int id, CancellationToken cancellationToken = default);
        Task<List<Entities.Competition.Competition>> GetListAsync(string? status, string? type, bool? isPublic, string? keyword, CancellationToken cancellationToken = default);
        Task AddAsync(Entities.Competition.Competition competition, CancellationToken cancellationToken = default);
        Task CreateWithJudgeAsync(Entities.Competition.Competition competition, CompetitionJudge judge, CancellationToken cancellationToken = default);
        Task UpdateAsync(Entities.Competition.Competition competition, CancellationToken cancellationToken = default);
        Task<bool> ExistsAsync(int id, CancellationToken cancellationToken = default);
    }
}
