using System;
using SystemService.DAL.Entities.Identity;

namespace SystemService.DAL.Entities.Competition
{
    public class CompetitionTeamMember
    {
        public long TeamMemberId { get; set; }
        public int TeamId { get; set; }
        public int UserId { get; set; }
        public DateTime JoinedAt { get; set; } = DateTime.UtcNow;

        public CompetitionTeam Team { get; set; } = null!;
        public User User { get; set; } = null!;
    }
}
