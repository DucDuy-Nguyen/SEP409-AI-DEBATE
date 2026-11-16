using System;
using SystemService.DAL.Entities.Identity;
using SystemService.DAL.Entities.Debate;

namespace SystemService.DAL.Entities.Competition
{
    public class JudgeScore
    {
        public long JudgeScoreId { get; set; }
        public int CompetitionMatchId { get; set; }
        public int? JudgeUserId { get; set; }
        public long MatchParticipantId { get; set; }
        public int CriteriaId { get; set; }
        public int? DebateRoundId { get; set; }
        public string ScoreSource { get; set; } = "JUDGE";
        public decimal Score { get; set; }
        public string? Feedback { get; set; }
        public DateTime CreatedAt { get; set; } = DateTime.UtcNow;

        // Navigation Properties
        public CompetitionMatch Match { get; set; } = null!;
        public User? JudgeUser { get; set; }
        public MatchParticipant Participant { get; set; } = null!;
        public DebateCriteria Criteria { get; set; } = null!;
        public DebateRound? DebateRound { get; set; }
    }
}
