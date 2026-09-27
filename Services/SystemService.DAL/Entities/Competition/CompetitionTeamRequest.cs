using System;
using SystemService.DAL.Entities.Identity;

namespace SystemService.DAL.Entities.Competition
{
    public class CompetitionTeamRequest
    {
        public long RequestId { get; set; }
        public int TeamId { get; set; }
        public int UserId { get; set; }
        public int CreatedByUserId { get; set; }
        public string RequestType { get; set; } = null!; // Invitation or JoinRequest
        public string Status { get; set; } = "Pending"; // Pending, Accepted, Rejected, Cancelled
        public string? Note { get; set; }
        public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
        public DateTime? RespondedAt { get; set; }
        public int? RespondedByUserId { get; set; }

        public CompetitionTeam Team { get; set; } = null!;
        public User User { get; set; } = null!;
        public User Creator { get; set; } = null!;
        public User? Responder { get; set; }
    }
}
