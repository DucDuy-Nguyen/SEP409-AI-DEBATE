using System;
using System.Collections.Generic;
using SystemService.DAL.Entities.Identity;

namespace SystemService.DAL.Entities.Competition
{
    public class CompetitionTeam
    {
        public int TeamId { get; set; }
        public int CompetitionId { get; set; }
        public string TeamName { get; set; } = null!;
        public int CaptainUserId { get; set; }
        public string Status { get; set; } = "Active";
        public DateTime CreatedAt { get; set; } = DateTime.UtcNow;

        public Competition Competition { get; set; } = null!;
        public User Captain { get; set; } = null!;
        public ICollection<CompetitionTeamMember> TeamMembers { get; set; } = new List<CompetitionTeamMember>();
    }
}
