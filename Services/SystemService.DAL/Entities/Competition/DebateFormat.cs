using System;

namespace SystemService.DAL.Entities.Competition
{
    public class DebateFormat
    {
        public int FormatId { get; set; }
        public string FormatName { get; set; } = null!;
        public string? Description { get; set; }
        public int MaxParticipants { get; set; } = 2;
        public int TotalRounds { get; set; } = 3;
        public int? RoundDurationSeconds { get; set; }
        public bool IsActive { get; set; } = true;
        public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
    }
}
