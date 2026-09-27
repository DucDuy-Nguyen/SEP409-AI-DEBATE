using System;

namespace SystemService.BLL.DTOs.Competition.Management
{
    public class CompetitionListItemResponse
    {
        public int CompetitionId { get; set; }
        public string Title { get; set; } = null!;
        public string CompetitionType { get; set; } = null!;
        public DateTime RegistrationStart { get; set; }
        public DateTime RegistrationEnd { get; set; }
        public DateTime StartDate { get; set; }
        public string Status { get; set; } = null!;
        public bool IsPublic { get; set; }
    }
}
