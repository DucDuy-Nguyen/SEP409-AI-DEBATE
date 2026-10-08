using System;
using System.Collections.Generic;
using System.ComponentModel.DataAnnotations.Schema;
using SystemService.DAL.Entities.Debate.Enums;
using SystemService.DAL.Entities.Identity;

namespace SystemService.DAL.Entities.Debate
{
    public class DebateSession
    {
        public int DebateSessionId { get; set; }
        public int TopicId { get; set; }
        public int FormatId { get; set; }
        public int CreatedBy { get; set; }
        public SessionStatus Status { get; set; } = SessionStatus.Waiting;
        [NotMapped]
        public int TurnTimeLimitSeconds { get; set; } = 180;
        public DateTime? StartTime { get; set; }
        public DateTime? EndTime { get; set; }
        public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
        public DateTime? UpdatedAt { get; set; }

        public Topic Topic { get; set; } = null!;
        public DebateFormat Format { get; set; } = null!;
        public User CreatedByUser { get; set; } = null!;
        public ICollection<DebateParticipant> Participants { get; set; } = new List<DebateParticipant>();
        public ICollection<DebateRound> DebateRounds { get; set; } = new List<DebateRound>();
    }
}
