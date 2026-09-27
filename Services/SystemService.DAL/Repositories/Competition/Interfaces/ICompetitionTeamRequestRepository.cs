using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using SystemService.DAL.Entities.Competition;

namespace SystemService.DAL.Repositories.Competition.Interfaces
{
    public interface ICompetitionTeamRequestRepository
    {
        Task<CompetitionTeamRequest?> GetByIdAsync(long requestId, CancellationToken cancellationToken = default);
        Task<bool> HasPendingRequestAsync(int teamId, int userId, CancellationToken cancellationToken = default);
        Task<List<CompetitionTeamRequest>> GetMyPendingInvitationsAsync(int competitionId, int userId, CancellationToken cancellationToken = default);
        Task<List<CompetitionTeamRequest>> GetTeamJoinRequestsAsync(int teamId, CancellationToken cancellationToken = default);
        Task AddRequestAsync(CompetitionTeamRequest request, CancellationToken cancellationToken = default);
        Task UpdateRequestAsync(CompetitionTeamRequest request, CancellationToken cancellationToken = default);
        Task AcceptInvitationWithMemberAsync(CompetitionTeamRequest request, CompetitionTeamMember member, int competitionId, int userId, CancellationToken cancellationToken = default);
        Task ApproveJoinRequestWithMemberAsync(CompetitionTeamRequest request, CompetitionTeamMember member, int competitionId, int userId, int captainUserId, CancellationToken cancellationToken = default);
    }
}
