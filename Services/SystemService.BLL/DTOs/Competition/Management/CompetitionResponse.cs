using System;

namespace SystemService.BLL.DTOs.Competition.Management
{
    public class CompetitionResponse
    {
        public int CompetitionId { get; set; }
        public string Title { get; set; } = null!;
        public string? Description { get; set; }
        public int CreatedBy { get; set; }
        public string CompetitionType { get; set; } = null!;
        public int? FormatId { get; set; }
        public int? MaxParticipants { get; set; }
        public DateTime RegistrationStart { get; set; }
        public DateTime RegistrationEnd { get; set; }
        public DateTime StartDate { get; set; }
        public DateTime? EndDate { get; set; }
        public string Status { get; set; } = null!;
        public bool IsPublic { get; set; }
        public DateTime CreatedAt { get; set; }
        public DateTime? UpdatedAt { get; set; }
    }
}
