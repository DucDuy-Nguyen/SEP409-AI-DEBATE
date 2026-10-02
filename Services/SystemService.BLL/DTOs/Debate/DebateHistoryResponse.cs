using System;
using SystemService.DAL.Entities.Debate.Enums;

namespace SystemService.BLL.DTOs.Debate
{
    public class DebateHistoryItemDto
    {
        public int SessionId { get; set; }
        public string Title { get; set; } = null!;
        public string Topic { get; set; } = null!;
        public DebateType DebateType { get; set; }
        public SessionStatus Status { get; set; }
        public DebateSide UserSide { get; set; }
        public DateTime CreatedAt { get; set; }
        public DateTime? EndedAt { get; set; }
    }
}
