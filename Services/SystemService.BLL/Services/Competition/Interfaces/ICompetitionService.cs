using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using SystemService.BLL.Common.Responses;
using SystemService.BLL.DTOs.Competition.Management;

namespace SystemService.BLL.Services.Competition.Interfaces
{
    public interface ICompetitionService
    {
        Task<ApiResponse<CompetitionResponse>> CreateAsync(int createdByUserId, CreateCompetitionRequest request, CancellationToken cancellationToken = default);
        Task<ApiResponse<CompetitionResponse>> UpdateAsync(int competitionId, int currentUserId, UpdateCompetitionRequest request, CancellationToken cancellationToken = default);
        Task<ApiResponse<CompetitionDetailResponse>> GetByIdAsync(int competitionId, CancellationToken cancellationToken = default);
        Task<ApiResponse<List<CompetitionListItemResponse>>> GetListAsync(CompetitionQueryRequest query, CancellationToken cancellationToken = default);
        Task<ApiResponse<object>> OpenRegistrationAsync(int competitionId, int currentUserId, CancellationToken cancellationToken = default);
        Task<ApiResponse<object>> CloseRegistrationAsync(int competitionId, int currentUserId, CancellationToken cancellationToken = default);
        Task<ApiResponse<object>> StartCompetitionAsync(int competitionId, int currentUserId, CancellationToken cancellationToken = default);
        Task<ApiResponse<object>> CompleteCompetitionAsync(int competitionId, int currentUserId, CancellationToken cancellationToken = default);
        Task<ApiResponse<object>> CancelCompetitionAsync(int competitionId, int currentUserId, CancellationToken cancellationToken = default);
    }
}
