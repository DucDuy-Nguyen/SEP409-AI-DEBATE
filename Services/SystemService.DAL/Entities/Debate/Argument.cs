using System;
using SystemService.DAL.Entities.Debate.Enums;

namespace SystemService.DAL.Entities.Debate
{
    public class Argument
    {
        public int ArgumentId { get; set; }
        public int RoundId { get; set; }
        public int ParticipantId { get; set; }
        public string Content { get; set; } = null!;
        public int? WordCount { get; set; }
        public int? DurationSeconds { get; set; }
        public DateTime SubmittedAt { get; set; } = DateTime.UtcNow;

        public DebateRound Round { get; set; } = null!;
        public DebateParticipant Participant { get; set; } = null!;
    }
}
