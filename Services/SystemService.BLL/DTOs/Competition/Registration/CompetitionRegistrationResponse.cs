using System;

namespace SystemService.BLL.DTOs.Competition.Registration
{
    public class CompetitionRegistrationResponse
    {
        public long RegistrationId { get; set; }
        public int CompetitionId { get; set; }
        public int UserId { get; set; }
        public string UserName { get; set; } = string.Empty;
        public string UserEmail { get; set; } = string.Empty;
        public string Status { get; set; } = null!;
        public string? Note { get; set; }
        public DateTime RegisteredAt { get; set; }
        public int? ReviewedBy { get; set; }
        public string? ReviewedByName { get; set; }
        public DateTime? ReviewedAt { get; set; }
    }
}
