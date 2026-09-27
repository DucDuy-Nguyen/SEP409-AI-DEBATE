using System;

namespace SystemService.BLL.DTOs.Competition.Team
{
    public class CompetitionTeamRequestResponse
    {
        public long RequestId { get; set; }
        public int TeamId { get; set; }
        public string TeamName { get; set; } = null!;
        public int UserId { get; set; }
        public string UserName { get; set; } = null!;
        public int CreatedByUserId { get; set; }
        public string CreatedByName { get; set; } = null!;
        public string RequestType { get; set; } = null!;
        public string Status { get; set; } = null!;
        public string? Note { get; set; }
        public DateTime CreatedAt { get; set; }
        public DateTime? RespondedAt { get; set; }
        public int? RespondedByUserId { get; set; }
        public string? RespondedByName { get; set; }
    }
}
