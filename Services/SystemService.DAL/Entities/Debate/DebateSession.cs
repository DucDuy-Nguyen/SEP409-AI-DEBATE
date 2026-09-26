using System;
using System.Collections.Generic;
using SystemService.DAL.Entities.Debate.Enums;
using SystemService.DAL.Entities.Identity;

namespace SystemService.DAL.Entities.Debate
{
    public class DebateSession
    {
        public int SessionId { get; set; }
        public string Title { get; set; } = null!;
        public string Topic { get; set; } = null!;
        public DebateType DebateType { get; set; }
        public string? Difficulty { get; set; }
        public DebateStage CurrentStage { get; set; } = DebateStage.Opening;
        public DebateSide CurrentTurnSide { get; set; } = DebateSide.Affirmative;
        public SessionStatus Status { get; set; } = SessionStatus.Created;
        public int CreatedByUserId { get; set; }
        public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
        public DateTime? StartedAt { get; set; }
        public DateTime? EndedAt { get; set; }

        public User CreatedByUser { get; set; } = null!;
        public ICollection<DebateParticipant> Participants { get; set; } = new List<DebateParticipant>();
        public ICollection<DebateTurn> Turns { get; set; } = new List<DebateTurn>();
    }
}
