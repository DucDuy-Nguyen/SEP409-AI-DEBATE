using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using SystemService.DAL.Entities.Competition;

namespace SystemService.DAL.Repositories.Competition.Interfaces
{
    public interface ICompetitionRegistrationRepository
    {
        Task<CompetitionRegistration?> GetByIdAsync(long id, CancellationToken cancellationToken = default);
        Task<CompetitionRegistration?> GetByCompetitionAndUserAsync(int competitionId, int userId, CancellationToken cancellationToken = default);
        Task<List<CompetitionRegistration>> GetListByCompetitionAsync(int competitionId, string? status, CancellationToken cancellationToken = default);
        Task<bool> HasUserRegisteredAsync(int competitionId, int userId, CancellationToken cancellationToken = default);
        Task AddAsync(CompetitionRegistration registration, CancellationToken cancellationToken = default);
        Task UpdateAsync(CompetitionRegistration registration, CancellationToken cancellationToken = default);
    }
}
