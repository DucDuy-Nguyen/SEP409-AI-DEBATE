using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using SystemService.BLL.Common.Responses;
using SystemService.BLL.DTOs.Debate;

namespace SystemService.BLL.Services.Debate.Interfaces
{
    public interface IDebateChallengeService
    {
        Task<ApiResponse<ChallengeResponse>> CreateChallengeAsync(int challengerUserId, CreateChallengeRequest request, CancellationToken cancellationToken = default);
        Task<ApiResponse<List<ChallengeResponse>>> GetReceivedChallengesAsync(int userId, CancellationToken cancellationToken = default);
        Task<ApiResponse<List<ChallengeResponse>>> GetSentChallengesAsync(int userId, CancellationToken cancellationToken = default);
        Task<ApiResponse<ChallengeResponse>> GetChallengeByIdAsync(int userId, int challengeId, CancellationToken cancellationToken = default);
        Task<ApiResponse<ChallengeResponse>> AcceptChallengeAsync(int userId, int challengeId, CancellationToken cancellationToken = default);
        Task<ApiResponse<ChallengeResponse>> RejectChallengeAsync(int userId, int challengeId, CancellationToken cancellationToken = default);
        Task<ApiResponse<ChallengeResponse>> CancelChallengeAsync(int userId, int challengeId, CancellationToken cancellationToken = default);
    }
}
