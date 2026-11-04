using System;
using System.Collections.Generic;
using SystemService.DAL.Entities.Identity;

namespace SystemService.DAL.Entities.Competition
{
    public class MatchParticipant
    {
        public long MatchParticipantId { get; set; }
        public int CompetitionMatchId { get; set; }
        public int? UserId { get; set; }
        public int? TeamId { get; set; }
        public string Side { get; set; } = null!;
        public int? SeedNumber { get; set; }
        public decimal? FinalScore { get; set; }
        public bool IsWinner { get; set; } = false;
        public DateTime CreatedAt { get; set; } = DateTime.UtcNow;

        // Navigation Properties
        public CompetitionMatch Match { get; set; } = null!;
        public User? User { get; set; }
        public CompetitionTeam? Team { get; set; }
        public ICollection<JudgeScore> JudgeScores { get; set; } = new List<JudgeScore>();
    }
}
