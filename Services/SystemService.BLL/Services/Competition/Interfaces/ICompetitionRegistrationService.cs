using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using SystemService.BLL.Common.Responses;
using SystemService.BLL.DTOs.Competition.Registration;

namespace SystemService.BLL.Services.Competition.Interfaces
{
    public interface ICompetitionRegistrationService
    {
        Task<ApiResponse<CompetitionRegistrationResponse>> RegisterAsync(int competitionId, int currentUserId, CancellationToken cancellationToken = default);
        Task<ApiResponse<List<CompetitionRegistrationResponse>>> GetListAsync(int competitionId, string? status, CancellationToken cancellationToken = default);
        Task<ApiResponse<CompetitionRegistrationResponse>> GetByIdAsync(int competitionId, long registrationId, CancellationToken cancellationToken = default);
        Task<ApiResponse<CompetitionRegistrationResponse>> ApproveAsync(int competitionId, long registrationId, int reviewerUserId, CancellationToken cancellationToken = default);
        Task<ApiResponse<CompetitionRegistrationResponse>> RejectAsync(int competitionId, long registrationId, int reviewerUserId, RejectRegistrationRequest request, CancellationToken cancellationToken = default);
        Task<ApiResponse<object>> CancelMyRegistrationAsync(int competitionId, int currentUserId, CancelRegistrationRequest request, CancellationToken cancellationToken = default);
        Task<ApiResponse<CompetitionRegistrationResponse>> RemoveParticipantAsync(int competitionId, long registrationId, int operatorUserId, UpdateRegistrationStatusRequest request, CancellationToken cancellationToken = default);
    }
}
