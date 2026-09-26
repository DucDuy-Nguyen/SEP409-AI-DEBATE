using Microsoft.EntityFrameworkCore;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using SystemService.DAL.Context;
using SystemService.DAL.Entities.Debate;
using SystemService.DAL.Entities.Debate.Enums;
using SystemService.DAL.Repositories.Debate.Interfaces;

namespace SystemService.DAL.Repositories.Debate.Implementations
{
    public class DebateChallengeRepository : IDebateChallengeRepository
    {
        private readonly SystemDbContext _context;

        public DebateChallengeRepository(SystemDbContext context)
        {
            _context = context;
        }

        public async Task<DebateChallenge> AddChallengeAsync(DebateChallenge challenge, CancellationToken cancellationToken = default)
        {
            await _context.DebateChallenges.AddAsync(challenge, cancellationToken);
            await _context.SaveChangesAsync(cancellationToken);
            return challenge;
        }

        public async Task<DebateChallenge?> GetChallengeByIdAsync(int challengeId, CancellationToken cancellationToken = default)
        {
            return await _context.DebateChallenges
                .FirstOrDefaultAsync(c => c.ChallengeId == challengeId, cancellationToken);
        }

        public async Task<DebateChallenge?> GetChallengeWithDetailsAsync(int challengeId, CancellationToken cancellationToken = default)
        {
            return await _context.DebateChallenges
                .Include(c => c.ChallengerUser)
                .Include(c => c.ChallengedUser)
                .Include(c => c.DebateSession)
                .FirstOrDefaultAsync(c => c.ChallengeId == challengeId, cancellationToken);
        }

        public async Task<List<DebateChallenge>> GetSentChallengesAsync(int userId, CancellationToken cancellationToken = default)
        {
            return await _context.DebateChallenges
                .Include(c => c.ChallengedUser)
                .Include(c => c.DebateSession)
                .Where(c => c.ChallengerUserId == userId)
                .OrderByDescending(c => c.CreatedAt)
                .ToListAsync(cancellationToken);
        }

        public async Task<List<DebateChallenge>> GetReceivedChallengesAsync(int userId, CancellationToken cancellationToken = default)
        {
            return await _context.DebateChallenges
                .Include(c => c.ChallengerUser)
                .Include(c => c.DebateSession)
                .Where(c => c.ChallengedUserId == userId)
                .OrderByDescending(c => c.CreatedAt)
                .ToListAsync(cancellationToken);
        }

        public async Task<bool> HasPendingChallengeBetweenUsersAsync(int userA, int userB, CancellationToken cancellationToken = default)
        {
            return await _context.DebateChallenges
                .AnyAsync(c => c.Status == ChallengeStatus.Pending
                            && ((c.ChallengerUserId == userA && c.ChallengedUserId == userB) ||
                                (c.ChallengerUserId == userB && c.ChallengedUserId == userA)), cancellationToken);
        }

        public async Task UpdateChallengeAsync(DebateChallenge challenge, CancellationToken cancellationToken = default)
        {
            _context.DebateChallenges.Update(challenge);
            await _context.SaveChangesAsync(cancellationToken);
        }
    }
}
