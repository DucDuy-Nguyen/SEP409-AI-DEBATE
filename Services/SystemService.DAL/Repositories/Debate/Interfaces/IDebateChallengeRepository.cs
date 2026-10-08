using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using SystemService.DAL.Entities.Debate;

namespace SystemService.DAL.Repositories.Debate.Interfaces
{
    public interface IDebateChallengeRepository
    {
        Task<DebateChallenge> AddChallengeAsync(DebateChallenge challenge, CancellationToken cancellationToken = default);
        Task<DebateChallenge?> GetChallengeByIdAsync(int challengeId, CancellationToken cancellationToken = default);
        Task<DebateChallenge?> GetChallengeWithDetailsAsync(int challengeId, CancellationToken cancellationToken = default);
        Task<List<DebateChallenge>> GetSentChallengesAsync(int userId, CancellationToken cancellationToken = default);
        Task<List<DebateChallenge>> GetReceivedChallengesAsync(int userId, CancellationToken cancellationToken = default);
        Task<bool> HasPendingChallengeBetweenUsersAsync(int userA, int userB, CancellationToken cancellationToken = default);
        Task UpdateChallengeAsync(DebateChallenge challenge, CancellationToken cancellationToken = default);
    }
}
