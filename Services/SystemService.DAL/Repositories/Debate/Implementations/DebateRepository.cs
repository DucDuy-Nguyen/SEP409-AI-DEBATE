using System;
using System.Collections.Generic;
using System.Data;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Storage;
using SystemService.DAL.Context;
using SystemService.DAL.Entities.Competition;
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
                .Include(s => s.AIJudgements)
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

        public async Task UpdateParticipantAsync(DebateParticipant participant, CancellationToken cancellationToken = default)
        {
            _context.DebateParticipants.Update(participant);
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

        public async Task<DebateFormat> GetOrCreateFormatAsync(string formatName, int maxParticipants, int totalRounds = 3, int roundDurationSeconds = 180, CancellationToken cancellationToken = default)
        {
            var format = await _context.DebateFormats.FirstOrDefaultAsync(f => f.FormatName.ToLower() == formatName.ToLower(), cancellationToken);
            if (format != null)
            {
                return format;
            }

            var newFormat = new DebateFormat
            {
                FormatName = formatName,
                MaxParticipants = maxParticipants,
                TotalRounds = totalRounds,
                RoundDurationSeconds = roundDurationSeconds,
                IsActive = true,
                CreatedAt = System.DateTime.UtcNow
            };

            await _context.DebateFormats.AddAsync(newFormat, cancellationToken);
            await _context.SaveChangesAsync(cancellationToken);
            return newFormat;
        }

        public async Task<IDbContextTransaction> BeginTransactionAsync(IsolationLevel isolationLevel, CancellationToken cancellationToken = default)
        {
            return await _context.Database.BeginTransactionAsync(isolationLevel, cancellationToken);
        }

        public void ClearChangeTracker()
        {
            _context.ChangeTracker.Clear();
        }

        public bool IsSessionInCompetition(int debateSessionId)
        {
            return _context.CompetitionMatches.Any(m => m.DebateSessionId == debateSessionId);
        }

        public async Task<bool> IsSessionInCompetitionAsync(int debateSessionId, CancellationToken cancellationToken = default)
        {
            return await _context.CompetitionMatches.AnyAsync(m => m.DebateSessionId == debateSessionId, cancellationToken);
        }

        public async Task<CompetitionMatch?> GetLinkedCompetitionMatchAsync(int debateSessionId, CancellationToken cancellationToken = default)
        {
            return await _context.CompetitionMatches
                .Include(m => m.Competition)
                .FirstOrDefaultAsync(m => m.DebateSessionId == debateSessionId, cancellationToken);
        }

        public async Task UpdateLinkedMatchStatusOnSessionCompleteAsync(int debateSessionId, DateTime completedAt, CancellationToken cancellationToken = default)
        {
            var linkedMatch = await _context.CompetitionMatches
                .FirstOrDefaultAsync(m => m.DebateSessionId == debateSessionId && m.Status == "Ongoing", cancellationToken);
            if (linkedMatch != null)
            {
                linkedMatch.Status = "Evaluating";
                linkedMatch.UpdatedAt = completedAt;
                await _context.SaveChangesAsync(cancellationToken);
            }
        }

        public async Task<bool> ClaimAndStartSessionAsync(int debateSessionId, DateTime startTime, int? linkedMatchId = null, CancellationToken cancellationToken = default)
        {
            var claimed = await _context.DebateSessions
                .Where(s => s.DebateSessionId == debateSessionId && s.Status == SessionStatus.Waiting)
                .ExecuteUpdateAsync(setters => setters
                    .SetProperty(s => s.Status, SessionStatus.InProgress)
                    .SetProperty(s => s.StartTime, startTime), cancellationToken);

            if (claimed != 1)
            {
                return false;
            }

            var firstRound = await _context.DebateRounds
                .FirstOrDefaultAsync(r => r.DebateSessionId == debateSessionId && r.RoundNumber == 1, cancellationToken);
            if (firstRound != null)
            {
                firstRound.StartTime = startTime;
            }

            if (linkedMatchId.HasValue)
            {
                var matchClaimed = await _context.CompetitionMatches
                    .Where(m => m.CompetitionMatchId == linkedMatchId.Value && m.Status == "Ready")
                    .ExecuteUpdateAsync(setters => setters
                        .SetProperty(m => m.Status, "Ongoing")
                        .SetProperty(m => m.StartedAt, startTime)
                        .SetProperty(m => m.UpdatedAt, startTime), cancellationToken);

                if (matchClaimed != 1)
                {
                    return false;
                }
            }

            await _context.SaveChangesAsync(cancellationToken);
            _context.ChangeTracker.Clear();
            return true;
        }

        public async Task AddAIJudgementAsync(AIJudgement judgement, CancellationToken cancellationToken = default)
        {
            await _context.AIJudgements.AddAsync(judgement, cancellationToken);
            await _context.SaveChangesAsync(cancellationToken);
        }

        public async Task<AIJudgement?> GetLatestAIJudgementAsync(int debateSessionId, CancellationToken cancellationToken = default)
        {
            return await _context.AIJudgements
                .Include(j => j.WinnerParticipant)
                .Where(j => j.DebateSessionId == debateSessionId)
                .OrderByDescending(j => j.CreatedAt)
                .FirstOrDefaultAsync(cancellationToken);
        }
    }
}
