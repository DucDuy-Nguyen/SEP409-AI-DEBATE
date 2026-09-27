using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using SystemService.BLL.Common.Responses;
using SystemService.BLL.DTOs.Competition.Team;

namespace SystemService.BLL.Services.Competition.Interfaces
{
    public interface ICompetitionTeamRequestService
    {
        Task<ApiResponse<CompetitionTeamRequestResponse>> SendInvitationAsync(int competitionId, int teamId, int captainUserId, SendTeamInvitationRequest request, CancellationToken cancellationToken = default);
        Task<ApiResponse<List<CompetitionTeamRequestResponse>>> GetMyInvitationsAsync(int competitionId, int currentUserId, CancellationToken cancellationToken = default);
        Task<ApiResponse<object>> AcceptInvitationAsync(int competitionId, long requestId, int currentUserId, CancellationToken cancellationToken = default);
        Task<ApiResponse<object>> RejectInvitationAsync(int competitionId, long requestId, int currentUserId, RejectTeamRequestDto request, CancellationToken cancellationToken = default);
        Task<ApiResponse<CompetitionTeamRequestResponse>> CreateJoinRequestAsync(int competitionId, int teamId, int currentUserId, CancellationToken cancellationToken = default);
        Task<ApiResponse<List<CompetitionTeamRequestResponse>>> GetTeamJoinRequestsAsync(int competitionId, int teamId, int captainUserId, CancellationToken cancellationToken = default);
        Task<ApiResponse<object>> ApproveJoinRequestAsync(int competitionId, int teamId, long requestId, int captainUserId, CancellationToken cancellationToken = default);
        Task<ApiResponse<object>> RejectJoinRequestAsync(int competitionId, int teamId, long requestId, int captainUserId, RejectTeamRequestDto request, CancellationToken cancellationToken = default);
    }
}
