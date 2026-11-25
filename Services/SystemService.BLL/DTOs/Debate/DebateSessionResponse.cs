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
        // Chu de kho fact de FE gui `topic` cho AI Evaluator (education|environment|technology|society), null neu Category khac
        public string? EvidenceTopic { get; set; }
        public DebateType DebateType { get; set; }
        // Seats of the room, from its format (1v1 = 2, 2v2 = 4), not the people already in it: a 2v2 that has only
        // its creator yet is still a team debate. DebateType does not tell (2v2 reports P2pMatch).
        public int MaxParticipants { get; set; }
        public bool IsTeamDebate { get; set; }
        public string? Difficulty { get; set; }
        public DebateStage CurrentStage { get; set; }
        public DebateSide CurrentTurnSide { get; set; }
        public SessionStatus Status { get; set; }
        public int CreatedByUserId { get; set; }
        public DateTime CreatedAt { get; set; }
        public DateTime? StartedAt { get; set; }
        public DateTime? EndedAt { get; set; }

        // Preparation minute before each round (see DebatePreparation): the current round (CurrentTurn.TurnOrder) starts
        // at PreparationEndsAt (UTC), no argument is accepted before. Compare it with ServerTime (UTC, when this response
        // was made), not with the browser clock. Past PreparationEndsAt = the current round is under way since then.
        public int PreparationSeconds { get; set; }
        public DateTime? PreparationEndsAt { get; set; }
        public bool IsPreparing { get; set; }
        // Only an AI practice may skip the preparation (POST /debate/{id}/skip-preparation).
        public bool CanSkipPreparation { get; set; }
        public int TotalRounds { get; set; }
        public DateTime ServerTime { get; set; }

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

        // 0-based index into DebateTurnOrder for 1v1 sessions (send as turnIndex to /ai-arguments); null for 2v2.
        public int? TurnIndex { get; set; }
        // "Mở đầu" / "Phản biện" / "Kết luận" for TurnOrder (round number) 1 / 2 / 3.
        public string RoundLabel { get; set; } = string.Empty;
        public int TimeLimitSeconds { get; set; }
        public TurnStatus Status { get; set; }
        public DateTime? StartedAt { get; set; }
    }
}
