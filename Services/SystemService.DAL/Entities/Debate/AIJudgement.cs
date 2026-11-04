using System;

namespace SystemService.DAL.Entities.Debate
{
    public class AIJudgement
    {
        public int JudgementId { get; set; }
        public int DebateSessionId { get; set; }
        public int? WinnerParticipantId { get; set; }
        public string? SuggestedWinnerSide { get; set; }
        public decimal? OverallScorePro { get; set; }
        public decimal? OverallScoreCon { get; set; }
        public decimal? OverallScore { get; set; }
        public decimal? ConfidenceScore { get; set; }
        public string? OverallFeedback { get; set; }
        public string? Summary { get; set; }
        public string? AIProvider { get; set; }
        public string? AIModel { get; set; }
        public string? RawResponseJson { get; set; }
        public DateTime CreatedAt { get; set; } = DateTime.UtcNow;

        // Navigation Properties
        public DebateSession DebateSession { get; set; } = null!;
        public DebateParticipant? WinnerParticipant { get; set; }
    }
}
