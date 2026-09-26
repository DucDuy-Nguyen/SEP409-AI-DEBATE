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
    public class DebateRepository : IDebateRepository
    {
        private readonly SystemDbContext _context;

        public DebateRepository(SystemDbContext context)
        {
            _context = context;
        }

        public async Task<DebateSession> AddSessionAsync(DebateSession session, CancellationToken cancellationToken = default)
        {
            await _context.DebateSessions.AddAsync(session, cancellationToken);
            await _context.SaveChangesAsync(cancellationToken);
            return session;
        }

        public async Task<DebateSession?> GetSessionByIdAsync(int sessionId, CancellationToken cancellationToken = default)
        {
            return await _context.DebateSessions
                .FirstOrDefaultAsync(s => s.SessionId == sessionId, cancellationToken);
        }

        public async Task<DebateSession?> GetSessionWithDetailsAsync(int sessionId, CancellationToken cancellationToken = default)
        {
            return await _context.DebateSessions
                .Include(s => s.CreatedByUser)
                .Include(s => s.Participants)
                    .ThenInclude(p => p.User)
                .Include(s => s.Turns.OrderBy(t => t.TurnOrder))
                    .ThenInclude(t => t.Arguments)
                        .ThenInclude(a => a.Participant)
                            .ThenInclude(p => p.User)
                .FirstOrDefaultAsync(s => s.SessionId == sessionId, cancellationToken);
        }

        public async Task<List<DebateSession>> GetUserSessionsAsync(int userId, CancellationToken cancellationToken = default)
        {
            return await _context.DebateSessions
                .Include(s => s.Participants)
                .Where(s => s.CreatedByUserId == userId || s.Participants.Any(p => p.UserId == userId))
                .OrderByDescending(s => s.CreatedAt)
                .ToListAsync(cancellationToken);
        }

        public async Task UpdateSessionAsync(DebateSession session, CancellationToken cancellationToken = default)
        {
            _context.DebateSessions.Update(session);
            await _context.SaveChangesAsync(cancellationToken);
        }

        public async Task AddParticipantAsync(DebateParticipant participant, CancellationToken cancellationToken = default)
        {
            await _context.DebateParticipants.AddAsync(participant, cancellationToken);
            await _context.SaveChangesAsync(cancellationToken);
        }

        public async Task<DebateParticipant?> GetParticipantByUserAsync(int sessionId, int userId, CancellationToken cancellationToken = default)
        {
            return await _context.DebateParticipants
                .FirstOrDefaultAsync(p => p.SessionId == sessionId && p.UserId == userId, cancellationToken);
        }

        public async Task<DebateParticipant?> GetParticipantBySideAsync(int sessionId, DebateSide side, CancellationToken cancellationToken = default)
        {
            return await _context.DebateParticipants
                .FirstOrDefaultAsync(p => p.SessionId == sessionId && p.Side == side, cancellationToken);
        }

        public async Task AddArgumentAsync(DebateArgument argument, CancellationToken cancellationToken = default)
        {
            await _context.DebateArguments.AddAsync(argument, cancellationToken);
            await _context.SaveChangesAsync(cancellationToken);
        }

        public async Task UpdateTurnAsync(DebateTurn turn, CancellationToken cancellationToken = default)
        {
            _context.DebateTurns.Update(turn);
            await _context.SaveChangesAsync(cancellationToken);
        }
    }
}
