using System;
using SystemService.DAL.Entities.Debate.Enums;

namespace SystemService.BLL.DTOs.Debate
{
    public class ChallengeUserSummaryDto
    {
        public int UserId { get; set; }
        public string FullName { get; set; } = string.Empty;
        public string Email { get; set; } = string.Empty;
    }

    public class ChallengeResponse
    {
        public int ChallengeId { get; set; }
        public ChallengeUserSummaryDto Challenger { get; set; } = null!;
        public ChallengeUserSummaryDto Challenged { get; set; } = null!;
        public string Topic { get; set; } = string.Empty;
        public DebateSide ChallengerPreferredSide { get; set; }
        public int TurnTimeLimitSeconds { get; set; }
        public ChallengeStatus Status { get; set; }
        public int? DebateSessionId { get; set; }
        public DateTime CreatedAt { get; set; }
        public DateTime? RespondedAt { get; set; }
        public DateTime? ExpiresAt { get; set; }
    }
}
