using System;
using SystemService.DAL.Entities.Debate.Enums;

namespace SystemService.DAL.Entities.Debate
{
    public class DebateArgument
    {
        public int ArgumentId { get; set; }
        public int TurnId { get; set; }
        public int ParticipantId { get; set; }
        public string Content { get; set; } = null!;
        public DateTime SubmittedAt { get; set; } = DateTime.UtcNow;

        public DebateTurn Turn { get; set; } = null!;
        public DebateParticipant Participant { get; set; } = null!;
    }
}
