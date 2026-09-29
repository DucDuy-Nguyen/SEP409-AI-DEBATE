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

        public async Task<DebateSession?> GetSessionByIdAsync(int debateSessionId, CancellationToken cancellationToken = default)
        {
            return await _context.DebateSessions
                .FirstOrDefaultAsync(s => s.DebateSessionId == debateSessionId, cancellationToken);
        }

        public async Task<DebateSession?> GetSessionWithDetailsAsync(int debateSessionId, CancellationToken cancellationToken = default)
        {
            return await _context.DebateSessions
                .Include(s => s.Topic)
                .Include(s => s.Format)
                .Include(s => s.CreatedByUser)
                .Include(s => s.Participants)
                    .ThenInclude(p => p.User)
                .Include(s => s.DebateRounds.OrderBy(r => r.RoundNumber))
                    .ThenInclude(r => r.Arguments)
                        .ThenInclude(a => a.Participant)
                            .ThenInclude(p => p.User)
                .FirstOrDefaultAsync(s => s.DebateSessionId == debateSessionId, cancellationToken);
        }

        public async Task<List<DebateSession>> GetUserSessionsAsync(int userId, CancellationToken cancellationToken = default)
        {
            return await _context.DebateSessions
                .Include(s => s.Topic)
                .Include(s => s.Format)
                .Include(s => s.Participants)
                .Where(s => s.CreatedBy == userId || s.Participants.Any(p => p.UserId == userId))
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

        public async Task<DebateParticipant?> GetParticipantByUserAsync(int debateSessionId, int userId, CancellationToken cancellationToken = default)
        {
            return await _context.DebateParticipants
                .FirstOrDefaultAsync(p => p.DebateSessionId == debateSessionId && p.UserId == userId, cancellationToken);
        }

        public async Task<DebateParticipant?> GetParticipantBySideAsync(int debateSessionId, DebateSide side, CancellationToken cancellationToken = default)
        {
            return await _context.DebateParticipants
                .FirstOrDefaultAsync(p => p.DebateSessionId == debateSessionId && p.Side == side, cancellationToken);
        }

        public async Task AddArgumentAsync(Argument argument, CancellationToken cancellationToken = default)
        {
            await _context.Arguments.AddAsync(argument, cancellationToken);
            await _context.SaveChangesAsync(cancellationToken);
        }

        public async Task AddRoundAsync(DebateRound round, CancellationToken cancellationToken = default)
        {
            await _context.DebateRounds.AddAsync(round, cancellationToken);
            await _context.SaveChangesAsync(cancellationToken);
        }

        public async Task UpdateRoundAsync(DebateRound round, CancellationToken cancellationToken = default)
        {
            _context.DebateRounds.Update(round);
            await _context.SaveChangesAsync(cancellationToken);
        }

        public async Task<Microsoft.EntityFrameworkCore.Storage.IDbContextTransaction> BeginTransactionAsync(CancellationToken cancellationToken = default)
        {
            return await _context.Database.BeginTransactionAsync(cancellationToken);
        }

        public async Task<Topic?> GetTopicByIdAsync(int topicId, CancellationToken cancellationToken = default)
        {
            return await _context.Topics.FirstOrDefaultAsync(t => t.TopicId == topicId, cancellationToken);
        }

        public async Task<Topic> GetOrCreateTopicAsync(string title, string? description, string difficulty, int createdBy, CancellationToken cancellationToken = default)
        {
            var existing = await _context.Topics.FirstOrDefaultAsync(
                t => t.Title.ToLower() == title.ToLower() && (description == null || t.Description == description), cancellationToken);
            if (existing != null)
            {
                return existing;
            }

            var newTopic = new Topic
            {
                Title = title,
                Description = description,
                Category = "General",
                Difficulty = string.IsNullOrWhiteSpace(difficulty) ? "Medium" : difficulty,
                CreatedBy = createdBy,
                IsActive = true,
                CreatedAt = System.DateTime.UtcNow
            };

            await _context.Topics.AddAsync(newTopic, cancellationToken);
            await _context.SaveChangesAsync(cancellationToken);
            return newTopic;
        }

        public async Task<DebateFormat?> GetFormatByIdAsync(int formatId, CancellationToken cancellationToken = default)
        {
            return await _context.DebateFormats.FirstOrDefaultAsync(f => f.FormatId == formatId, cancellationToken);
        }

        public async Task<DebateFormat?> GetFormatByNameAsync(string formatName, CancellationToken cancellationToken = default)
        {
            return await _context.DebateFormats.FirstOrDefaultAsync(f => f.FormatName.ToLower() == formatName.ToLower(), cancellationToken);
        }
    }
}
