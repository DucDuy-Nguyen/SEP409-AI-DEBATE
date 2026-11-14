using System.Threading;
using System.Threading.Tasks;

namespace SystemService.BLL.Services.Debate.Interfaces
{
    public interface IDebateRealtimeNotifier
    {
        Task NotifyUserJoinedAsync(int sessionId, int userId, string fullName, string side, CancellationToken cancellationToken = default);
        Task NotifyUserLeftAsync(int sessionId, int userId, string fullName, CancellationToken cancellationToken = default);
        Task NotifyArgumentSubmittedAsync(int sessionId, object argumentData, object? turnData, CancellationToken cancellationToken = default);
        Task NotifySessionStartedAsync(int sessionId, object sessionData, CancellationToken cancellationToken = default);
        Task NotifySessionStatusChangedAsync(int sessionId, string status, string? reason = null, CancellationToken cancellationToken = default);
    }
}

