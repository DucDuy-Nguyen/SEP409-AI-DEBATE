using System;
using SystemService.DAL.Entities.Debate.Enums;
using SystemService.DAL.Entities.Identity;

namespace SystemService.DAL.Entities.Debate
{
    public class DebateChallenge
    {
        public int ChallengeId { get; set; }

        public int ChallengerUserId { get; set; }
        public virtual User ChallengerUser { get; set; } = null!;

        public int ChallengedUserId { get; set; }
        public virtual User ChallengedUser { get; set; } = null!;

        public string Topic { get; set; } = string.Empty;

        public DebateSide ChallengerPreferredSide { get; set; }

        public int TurnTimeLimitSeconds { get; set; } = 180;

        public ChallengeStatus Status { get; set; } = ChallengeStatus.Pending;

        public int? DebateSessionId { get; set; }
        public virtual DebateSession? DebateSession { get; set; }

        public DateTime CreatedAt { get; set; } = DateTime.UtcNow;

        public DateTime? RespondedAt { get; set; }

        public DateTime? ExpiresAt { get; set; }
    }
}
