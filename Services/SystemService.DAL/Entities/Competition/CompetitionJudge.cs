using System;
using SystemService.DAL.Entities.Identity;

namespace SystemService.DAL.Entities.Competition
{
    public class CompetitionJudge
    {
        public int CompetitionJudgeId { get; set; }
        public int CompetitionId { get; set; }
        public int UserId { get; set; }
        public DateTime AssignedAt { get; set; } = DateTime.UtcNow;

        public Competition Competition { get; set; } = null!;
        public User User { get; set; } = null!;
    }
}
