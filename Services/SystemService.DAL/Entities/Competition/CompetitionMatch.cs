using System;
using System.Collections.Generic;
using SystemService.DAL.Entities.Identity;
using SystemService.DAL.Entities.Debate;

namespace SystemService.DAL.Entities.Competition
{
    public class CompetitionMatch
    {
        public int CompetitionMatchId { get; set; }
        public int CompetitionId { get; set; }
        public int CompetitionRoundId { get; set; }
        public int? DebateSessionId { get; set; }
        public int MatchNumber { get; set; }
        public int BracketPosition { get; set; } = 1;
        public int? NextMatchId { get; set; }
        public int? AssignedJudgeUserId { get; set; }
        public DateTime? ScheduledAt { get; set; }
        public DateTime? StartedAt { get; set; }
        public DateTime? CompletedAt { get; set; }
        public string Status { get; set; } = "Scheduled";
        public int? WinnerUserId { get; set; }
        public int? WinnerTeamId { get; set; }
        public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
        public DateTime? UpdatedAt { get; set; }
        public byte[] RowVersion { get; set; } = null!;

        // Navigation Properties
        public Competition Competition { get; set; } = null!;
        public CompetitionRound Round { get; set; } = null!;
        public DebateSession? DebateSession { get; set; }
        public User? WinnerUser { get; set; }
        public CompetitionTeam? WinnerTeam { get; set; }
        public CompetitionMatch? NextMatch { get; set; }
        public User? AssignedJudgeUser { get; set; }

        public ICollection<MatchParticipant> Participants { get; set; } = new List<MatchParticipant>();
        public ICollection<JudgeScore> JudgeScores { get; set; } = new List<JudgeScore>();
    }
}
