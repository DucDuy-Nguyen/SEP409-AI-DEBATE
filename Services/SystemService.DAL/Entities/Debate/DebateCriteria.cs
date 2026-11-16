using System;
using System.Collections.Generic;
using SystemService.DAL.Entities.Competition;

namespace SystemService.DAL.Entities.Debate
{
    public class DebateCriteria
    {
        public int CriteriaId { get; set; }
        public string CriterionCode { get; set; } = null!;
        public string CriteriaName { get; set; } = null!;
        public string? Description { get; set; }
        public decimal MaxScore { get; set; } = 10.0m;
        public decimal Weight { get; set; } = 1.0m;
        public bool IsActive { get; set; } = true;
        public DateTime CreatedAt { get; set; } = DateTime.UtcNow;

        // Navigation Properties
        public ICollection<JudgeScore> JudgeScores { get; set; } = new List<JudgeScore>();
    }
}
