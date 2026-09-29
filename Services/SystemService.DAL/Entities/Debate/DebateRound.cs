using System;
using System.Collections.Generic;
using SystemService.DAL.Entities.Debate.Enums;

namespace SystemService.DAL.Entities.Debate
{
    public class DebateRound
    {
        public int RoundId { get; set; }
        public int DebateSessionId { get; set; }
        public int RoundNumber { get; set; }
        public RoundType RoundType { get; set; }
        public DateTime? StartTime { get; set; }
        public DateTime? EndTime { get; set; }
        public DateTime CreatedAt { get; set; } = DateTime.UtcNow;

        public DebateSession DebateSession { get; set; } = null!;
        public ICollection<Argument> Arguments { get; set; } = new List<Argument>();
    }
}
