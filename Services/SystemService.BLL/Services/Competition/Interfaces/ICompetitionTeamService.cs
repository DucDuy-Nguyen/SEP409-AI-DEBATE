using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using SystemService.BLL.Common.Responses;
using SystemService.BLL.DTOs.Competition.Team;

namespace SystemService.BLL.Services.Competition.Interfaces
{
    public interface ICompetitionTeamService
    {
        Task<ApiResponse<CompetitionTeamResponse>> CreateTeamAsync(int competitionId, int captainUserId, CreateCompetitionTeamRequest request, CancellationToken cancellationToken = default);
        Task<ApiResponse<List<CompetitionTeamResponse>>> GetListAsync(int competitionId, CancellationToken cancellationToken = default);
        Task<ApiResponse<CompetitionTeamDetailResponse>> GetByIdAsync(int competitionId, int teamId, CancellationToken cancellationToken = default);
        Task<ApiResponse<object>> AddMemberAsync(int competitionId, int teamId, int currentUserId, AddCompetitionTeamMemberRequest request, CancellationToken cancellationToken = default);
        Task<ApiResponse<object>> RemoveMemberAsync(int competitionId, int teamId, int targetUserId, int currentUserId, CancellationToken cancellationToken = default);
        Task<ApiResponse<object>> WithdrawTeamAsync(int competitionId, int teamId, int currentUserId, CancellationToken cancellationToken = default);
    }
}
