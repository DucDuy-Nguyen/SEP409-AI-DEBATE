using System;

namespace SystemService.BLL.DTOs.Competition.Team
{
    public class CompetitionTeamResponse
    {
        public int TeamId { get; set; }
        public int CompetitionId { get; set; }
        public string TeamName { get; set; } = null!;
        public int CaptainUserId { get; set; }
        public string Status { get; set; } = null!;
        public DateTime CreatedAt { get; set; }
    }
}
