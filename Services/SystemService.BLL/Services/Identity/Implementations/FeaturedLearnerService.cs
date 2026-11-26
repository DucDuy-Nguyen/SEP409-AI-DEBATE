using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.EntityFrameworkCore;
using SystemService.BLL.Common.Responses;
using SystemService.BLL.DTOs.Identity.Users;
using SystemService.BLL.Services.Identity.Interfaces;
using SystemService.DAL.Context;
using SystemService.DAL.Entities.Debate.Enums;

namespace SystemService.BLL.Services.Identity.Implementations
{
    /// <summary>
    /// Featured learners: active Members (not Admin / Lecturer) ranked by the AI score of their side over the completed
    /// debates of the window (the latest AIJudgement of each debate), then by wins, then by debates. In a 2v2 both
    /// teammates get their side's score. A debate without a score for that side does not count.
    /// </summary>
    public class FeaturedLearnerService : IFeaturedLearnerService
    {
        private static readonly string[] StaffRoles = { "Admin", "Lecturer" };

        private readonly SystemDbContext _db;

        public FeaturedLearnerService(SystemDbContext db)
        {
            _db = db;
        }

        public async Task<ApiResponse<List<FeaturedLearnerDto>>> GetFeaturedLearnersAsync(FeaturedLearnersQuery query, CancellationToken cancellationToken = default)
        {
            int days = Math.Clamp(query.Days, 0, 365);
            int limit = Math.Clamp(query.Limit, 1, 20);
            int minDebates = Math.Clamp(query.MinDebates, 1, 50);
            DateTime? since = days == 0 ? null : DateTime.UtcNow.AddDays(-days);

            var participations = _db.DebateParticipants.AsNoTracking()
                .Where(p => p.UserId != null
                            && p.ParticipantType == ParticipantType.USER
                            && p.DebateSession.Status == SessionStatus.Completed
                            && p.User!.IsActive
                            && !p.User.UserRoles.Any(ur => StaffRoles.Contains(ur.Role.RoleName)));
            if (since != null)
            {
                participations = participations.Where(p => (p.DebateSession.EndTime ?? p.DebateSession.CreatedAt) >= since);
            }

            var rows = await participations
                .Select(p => new
                {
                    UserId = p.UserId!.Value,
                    p.DebateSessionId,
                    p.Side,
                    EndedAt = p.DebateSession.EndTime ?? p.DebateSession.CreatedAt,
                    Judgement = p.DebateSession.AIJudgements
                        .OrderByDescending(j => j.CreatedAt)
                        .ThenByDescending(j => j.JudgementId)
                        .Select(j => new { j.OverallScorePro, j.OverallScoreCon })
                        .FirstOrDefault(),
                })
                .ToListAsync(cancellationToken);

            var scored = rows
                .Where(r => r.Judgement != null)
                .Select(r =>
                {
                    bool isPro = r.Side == DebateSide.PRO;
                    decimal? mine = isPro ? r.Judgement!.OverallScorePro : r.Judgement!.OverallScoreCon;
                    decimal? theirs = isPro ? r.Judgement.OverallScoreCon : r.Judgement.OverallScorePro;
                    return new { r.UserId, r.DebateSessionId, r.EndedAt, Mine = mine, Won = mine != null && theirs != null && mine > theirs };
                })
                .Where(r => r.Mine != null)
                // one row per learner and debate, should a learner have two participations in one session
                .GroupBy(r => (r.UserId, r.DebateSessionId))
                .Select(g => g.First());

            var ranked = scored
                .GroupBy(r => r.UserId)
                .Select(g => new
                {
                    UserId = g.Key,
                    Debates = g.Count(),
                    Wins = g.Count(r => r.Won),
                    Average = g.Average(r => r.Mine!.Value),
                    Best = g.Max(r => r.Mine!.Value),
                    Last = g.Max(r => r.EndedAt),
                })
                .Where(x => x.Debates >= minDebates)
                .OrderByDescending(x => Math.Round(x.Average, 2))
                .ThenByDescending(x => x.Wins)
                .ThenByDescending(x => x.Debates)
                .ThenByDescending(x => x.Last)
                .ThenBy(x => x.UserId)
                .Take(limit)
                .ToList();

            var ids = ranked.Select(x => x.UserId).ToList();
            var users = await _db.Users.AsNoTracking()
                .Where(u => ids.Contains(u.UserId))
                .Select(u => new { u.UserId, u.FullName, u.AvatarUrl })
                .ToDictionaryAsync(u => u.UserId, cancellationToken);

            var result = ranked
                .Where(x => users.ContainsKey(x.UserId))
                .Select((x, i) => new FeaturedLearnerDto
                {
                    Rank = i + 1,
                    UserId = x.UserId,
                    FullName = users[x.UserId].FullName,
                    AvatarUrl = users[x.UserId].AvatarUrl,
                    DebatesCompleted = x.Debates,
                    Wins = x.Wins,
                    WinRate = Math.Round((decimal)x.Wins / x.Debates, 2),
                    AverageScore = Math.Round(x.Average, 2),
                    BestScore = Math.Round(x.Best, 2),
                    LastDebateAt = DateTime.SpecifyKind(x.Last, DateTimeKind.Utc),
                })
                .ToList();

            return ApiResponse<List<FeaturedLearnerDto>>.SuccessResponse(result, "Featured learners retrieved.");
        }
    }
}
