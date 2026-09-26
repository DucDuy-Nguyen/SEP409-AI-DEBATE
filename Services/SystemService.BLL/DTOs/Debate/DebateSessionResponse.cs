using System;
using System.Collections.Generic;
using SystemService.DAL.Entities.Debate.Enums;

namespace SystemService.BLL.DTOs.Debate
{
    public class DebateSessionResponse
    {
        public int SessionId { get; set; }
        public string Title { get; set; } = null!;
        public string Topic { get; set; } = null!;
        public DebateType DebateType { get; set; }
        public string? Difficulty { get; set; }
        public DebateStage CurrentStage { get; set; }
        public DebateSide CurrentTurnSide { get; set; }
        public SessionStatus Status { get; set; }
        public int CreatedByUserId { get; set; }
        public DateTime CreatedAt { get; set; }
        public DateTime? StartedAt { get; set; }
        public DateTime? EndedAt { get; set; }

        public List<ParticipantDto> Participants { get; set; } = new List<ParticipantDto>();
        public TurnDto? CurrentTurn { get; set; }
    }

    public class ParticipantDto
    {
        public int ParticipantId { get; set; }
        public int? UserId { get; set; }
        public string SpeakerName { get; set; } = null!;
        public bool IsAI { get; set; }
        public DebateSide Side { get; set; }
        public DateTime JoinedAt { get; set; }
    }

    public class TurnDto
    {
        public int TurnId { get; set; }
        public DebateStage Stage { get; set; }
        public DebateSide Side { get; set; }
        public int TurnOrder { get; set; }
        public int TimeLimitSeconds { get; set; }
        public TurnStatus Status { get; set; }
        public DateTime? StartedAt { get; set; }
    }
}
