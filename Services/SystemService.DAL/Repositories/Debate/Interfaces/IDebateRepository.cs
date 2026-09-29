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
        Task<DebateSession?> GetSessionByIdAsync(int debateSessionId, CancellationToken cancellationToken = default);
        Task<DebateSession?> GetSessionWithDetailsAsync(int debateSessionId, CancellationToken cancellationToken = default);
        Task<List<DebateSession>> GetUserSessionsAsync(int userId, CancellationToken cancellationToken = default);
        Task UpdateSessionAsync(DebateSession session, CancellationToken cancellationToken = default);
        Task AddParticipantAsync(DebateParticipant participant, CancellationToken cancellationToken = default);
        Task<DebateParticipant?> GetParticipantByUserAsync(int debateSessionId, int userId, CancellationToken cancellationToken = default);
        Task<DebateParticipant?> GetParticipantBySideAsync(int debateSessionId, DebateSide side, CancellationToken cancellationToken = default);
        Task AddArgumentAsync(Argument argument, CancellationToken cancellationToken = default);
        Task AddRoundAsync(DebateRound round, CancellationToken cancellationToken = default);
        Task UpdateRoundAsync(DebateRound round, CancellationToken cancellationToken = default);
        Task<Microsoft.EntityFrameworkCore.Storage.IDbContextTransaction> BeginTransactionAsync(CancellationToken cancellationToken = default);
        Task<Topic?> GetTopicByIdAsync(int topicId, CancellationToken cancellationToken = default);
        Task<Topic> GetOrCreateTopicAsync(string title, string? description, string difficulty, int createdBy, CancellationToken cancellationToken = default);
        Task<DebateFormat?> GetFormatByIdAsync(int formatId, CancellationToken cancellationToken = default);
        Task<DebateFormat?> GetFormatByNameAsync(string formatName, CancellationToken cancellationToken = default);
    }
}
