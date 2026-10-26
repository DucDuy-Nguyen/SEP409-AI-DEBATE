using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using SystemService.BLL.Common.Responses;
using SystemService.BLL.DTOs.Debate;

namespace SystemService.BLL.Services.Debate.Interfaces
{
    public interface IDebateService
    {
        Task<ApiResponse<DebateSessionResponse>> CreateAiPracticeSessionAsync(int userId, CreateAiPracticeSessionRequest request, CancellationToken cancellationToken = default);
        Task<ApiResponse<DebateSessionResponse>> CreateP2pSessionAsync(int userId, CreateP2pSessionRequest request, CancellationToken cancellationToken = default);
        Task<ApiResponse<DebateSessionResponse>> JoinP2pSessionAsync(int userId, int sessionId, JoinSessionRequest request, CancellationToken cancellationToken = default);
        Task<ApiResponse<DebateSessionResponse>> GetSessionDetailsAsync(int userId, int sessionId, CancellationToken cancellationToken = default);
        Task<ApiResponse<DebateSessionResponse>> SubmitArgumentAsync(int userId, int sessionId, SubmitArgumentRequest request, CancellationToken cancellationToken = default);
        Task<ApiResponse<DebateSessionResponse>> Create2v2SessionAsync(int userId, Create2v2SessionRequest request, CancellationToken cancellationToken = default);
        Task<ApiResponse<DebateSessionResponse>> Join2v2SessionAsync(int userId, int sessionId, Join2v2SessionRequest request, CancellationToken cancellationToken = default);
        Task<ApiResponse<DebateTranscriptResponse>> GetTranscriptAsync(int userId, int sessionId, CancellationToken cancellationToken = default);
        Task<ApiResponse<List<DebateHistoryItemDto>>> GetUserHistoryAsync(int userId, CancellationToken cancellationToken = default);

        Task<ApiResponse<DebateSessionResponse>> SwitchSideAsync(int userId, int sessionId, CancellationToken cancellationToken = default);
        Task<ApiResponse<bool>> SendSwapSideRequestAsync(int userId, int sessionId, SendSwapSideRequest request, CancellationToken cancellationToken = default);
        Task<ApiResponse<DebateSessionResponse>> RespondSwapSideRequestAsync(int userId, int sessionId, RespondSwapSideRequest request, CancellationToken cancellationToken = default);
        Task<ApiResponse<List<SideSwapRequestResponse>>> GetPendingSwapRequestsAsync(int userId, int sessionId, CancellationToken cancellationToken = default);
        Task<ApiResponse<DebateSessionResponse>> StartDebateSessionAsync(int userId, int sessionId, CancellationToken cancellationToken = default);

        Task<ApiResponse<DebateEvaluationResponse>> EvaluateSessionAsync(int userId, int sessionId, CancellationToken cancellationToken = default);
        Task<ApiResponse<DebateEvaluationResponse>> GetSessionEvaluationAsync(int userId, int sessionId, CancellationToken cancellationToken = default);
        Task<ApiResponse<SingleArgumentEvaluationResponse>> EvaluateArgumentAsync(int userId, int sessionId, int argumentId, CancellationToken cancellationToken = default);
    }
}
