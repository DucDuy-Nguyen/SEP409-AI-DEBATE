using System;
using System.Collections.Generic;

namespace SystemService.DAL.Entities.Debate
{
    public class DebateFormat
    {
        public int FormatId { get; set; }
        public string FormatName { get; set; } = null!;
        public string? Description { get; set; }
        public int MaxParticipants { get; set; } = 2;
        public int TotalRounds { get; set; } = 3;
        public int? RoundDurationSeconds { get; set; } = 180;
        public bool IsActive { get; set; } = true;
        public DateTime CreatedAt { get; set; } = DateTime.UtcNow;

        public ICollection<DebateSession> DebateSessions { get; set; } = new List<DebateSession>();
    }
}
