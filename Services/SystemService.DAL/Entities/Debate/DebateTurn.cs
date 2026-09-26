using System;
using System.Collections.Generic;
using SystemService.DAL.Entities.Debate.Enums;

namespace SystemService.DAL.Entities.Debate
{
    public class DebateTurn
    {
        public int TurnId { get; set; }
        public int SessionId { get; set; }
        public DebateStage Stage { get; set; }
        public DebateSide Side { get; set; }
        public int TurnOrder { get; set; }
        public int TimeLimitSeconds { get; set; } = 180;
        public TurnStatus Status { get; set; } = TurnStatus.Pending;
        public DateTime? StartedAt { get; set; }
        public DateTime? EndedAt { get; set; }

        public DebateSession Session { get; set; } = null!;
        public ICollection<DebateArgument> Arguments { get; set; } = new List<DebateArgument>();
    }
}
