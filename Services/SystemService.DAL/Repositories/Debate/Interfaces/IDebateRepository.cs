using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using SystemService.DAL.Entities.Debate;
using SystemService.DAL.Entities.Debate.Enums;

namespace SystemService.DAL.Repositories.Debate.Interfaces
{
    public interface IDebateRepository
    {
        Task<DebateSession> AddSessionAsync(DebateSession session, CancellationToken cancellationToken = default);
        Task<DebateSession?> GetSessionByIdAsync(int sessionId, CancellationToken cancellationToken = default);
        Task<DebateSession?> GetSessionWithDetailsAsync(int sessionId, CancellationToken cancellationToken = default);
        Task<List<DebateSession>> GetUserSessionsAsync(int userId, CancellationToken cancellationToken = default);
        Task UpdateSessionAsync(DebateSession session, CancellationToken cancellationToken = default);
        Task AddParticipantAsync(DebateParticipant participant, CancellationToken cancellationToken = default);
        Task<DebateParticipant?> GetParticipantByUserAsync(int sessionId, int userId, CancellationToken cancellationToken = default);
        Task<DebateParticipant?> GetParticipantBySideAsync(int sessionId, DebateSide side, CancellationToken cancellationToken = default);
        Task AddArgumentAsync(DebateArgument argument, CancellationToken cancellationToken = default);
        Task UpdateTurnAsync(DebateTurn turn, CancellationToken cancellationToken = default);
    }
}

