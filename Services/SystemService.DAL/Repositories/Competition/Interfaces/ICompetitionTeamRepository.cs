using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using SystemService.DAL.Entities.Competition;

namespace SystemService.DAL.Repositories.Competition.Interfaces
{
    public interface ICompetitionTeamRepository
    {
        Task<CompetitionTeam?> GetByIdAsync(int teamId, CancellationToken cancellationToken = default);
        Task<CompetitionTeam?> GetWithMembersAsync(int teamId, CancellationToken cancellationToken = default);
        Task<List<CompetitionTeam>> GetListByCompetitionAsync(int competitionId, CancellationToken cancellationToken = default);
        Task<bool> IsTeamNameExistsAsync(int competitionId, string teamName, CancellationToken cancellationToken = default);
        Task<bool> IsUserInTeamAsync(int teamId, int userId, CancellationToken cancellationToken = default);
        Task<CompetitionTeamMember?> GetTeamMemberAsync(int teamId, int userId, CancellationToken cancellationToken = default);
        Task AddTeamAsync(CompetitionTeam team, CancellationToken cancellationToken = default);
        Task AddMemberAsync(CompetitionTeamMember member, CancellationToken cancellationToken = default);
        Task RemoveMemberAsync(CompetitionTeamMember member, CancellationToken cancellationToken = default);
        Task UpdateTeamAsync(CompetitionTeam team, CancellationToken cancellationToken = default);
    }
}
