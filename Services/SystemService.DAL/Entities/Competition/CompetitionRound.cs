using System;
using System.Collections.Generic;

namespace SystemService.DAL.Entities.Competition
{
    public class CompetitionRound
    {
        public int CompetitionRoundId { get; set; }
        public int CompetitionId { get; set; }
        public int RoundNumber { get; set; }
        public string RoundName { get; set; } = null!;
        public string? RoundType { get; set; }
        public DateTime? StartDate { get; set; }
        public DateTime? EndDate { get; set; }
        public string Status { get; set; } = "Pending";
        public DateTime CreatedAt { get; set; } = DateTime.UtcNow;

        // Navigation Properties
        public Competition Competition { get; set; } = null!;
        public ICollection<CompetitionMatch> Matches { get; set; } = new List<CompetitionMatch>();
    }
}
