using System.Threading;
using System.Threading.Tasks;
using SystemService.BLL.Common.Responses;
using SystemService.BLL.DTOs.Debate;

namespace SystemService.BLL.Services.Competition.Interfaces
{
    public interface ICompetitionDebateBridgeService
    {
        Task<ApiResponse<DebateSessionResponse>> PrepareMatchDebateAsync(
            int userId, int matchId, int topicId, CancellationToken cancellationToken = default);
    }
}
