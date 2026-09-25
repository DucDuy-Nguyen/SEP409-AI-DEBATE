using System;

namespace SystemService.BLL.DTOs.Competition.Management
{
    public class UpdateCompetitionRequest
    {
        public string Title { get; set; } = null!;
        public string? Description { get; set; }
        public int? FormatId { get; set; }
        public int? MaxParticipants { get; set; }
        public DateTime RegistrationStart { get; set; }
        public DateTime RegistrationEnd { get; set; }
        public DateTime StartDate { get; set; }
        public DateTime? EndDate { get; set; }
        public bool IsPublic { get; set; } = true;
    }
}
