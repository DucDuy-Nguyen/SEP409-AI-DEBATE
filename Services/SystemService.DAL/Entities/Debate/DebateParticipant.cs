using System;
using System.Collections.Generic;
using SystemService.DAL.Entities.Debate.Enums;
using SystemService.DAL.Entities.Identity;

namespace SystemService.DAL.Entities.Debate
{
    public class DebateParticipant
    {
        public int ParticipantId { get; set; }
        public int DebateSessionId { get; set; }
        public int? UserId { get; set; }
        public ParticipantType ParticipantType { get; set; }
        public DebateSide Side { get; set; }
        public DateTime JoinedAt { get; set; } = DateTime.UtcNow;

        public DebateSession DebateSession { get; set; } = null!;
        public User? User { get; set; }
        public ICollection<Argument> Arguments { get; set; } = new List<Argument>();
    }
}
