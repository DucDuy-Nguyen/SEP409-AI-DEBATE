using System;
using System.Collections.Generic;
using SystemService.DAL.Entities.Identity;

namespace SystemService.DAL.Entities.Competition
{
    public class Competition
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
        public string Status { get; set; } = "Draft";
        public bool IsPublic { get; set; } = true;
        public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
        public DateTime? UpdatedAt { get; set; }

        public User Creator { get; set; } = null!;
        public ICollection<CompetitionRegistration> Registrations { get; set; } = new List<CompetitionRegistration>();
        public ICollection<CompetitionTeam> Teams { get; set; } = new List<CompetitionTeam>();
        public ICollection<CompetitionJudge> Judges { get; set; } = new List<CompetitionJudge>();
    }
}
