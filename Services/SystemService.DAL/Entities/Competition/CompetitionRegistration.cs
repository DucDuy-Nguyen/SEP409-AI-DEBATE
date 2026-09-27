using System;
using SystemService.DAL.Entities.Identity;

namespace SystemService.DAL.Entities.Competition
{
    public class CompetitionRegistration
    {
        public long RegistrationId { get; set; }
        public int CompetitionId { get; set; }
        public int UserId { get; set; }
        public string Status { get; set; } = "Pending";
        public string? Note { get; set; }
        public DateTime RegisteredAt { get; set; } = DateTime.UtcNow;
        public int? ReviewedBy { get; set; }
        public DateTime? ReviewedAt { get; set; }

        public Competition Competition { get; set; } = null!;
        public User User { get; set; } = null!;
        public User? Reviewer { get; set; }
    }
}
