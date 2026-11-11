using System;
using System.Collections.Generic;
using SystemService.BLL.DTOs.AI;
using SystemService.DAL.Entities.Debate.Enums;

namespace SystemService.BLL.DTOs.Debate
{
    public class DebateTranscriptResponse
    {
        public int SessionId { get; set; }
        public string Title { get; set; } = null!;
        public string Topic { get; set; } = null!;
        public SessionStatus Status { get; set; }
        public List<ArgumentDetailDto> Arguments { get; set; } = new List<ArgumentDetailDto>();
    }

    public class ArgumentDetailDto
    {
        public int ArgumentId { get; set; }
        public int TurnOrder { get; set; }
        public DebateStage Stage { get; set; }
        public DebateSide Side { get; set; }
        public int? UserId { get; set; }
        public string SpeakerName { get; set; } = null!;
        public bool IsAI { get; set; }
        public string Content { get; set; } = null!;
        public int? WordCount { get; set; }
        public int? DurationSeconds { get; set; }
        public DeliveryAnalyticsDto? DeliveryAnalytics { get; set; }
        public DateTime SubmittedAt { get; set; }
    }
}
