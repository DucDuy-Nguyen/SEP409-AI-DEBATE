using System;

namespace SystemService.BLL.DTOs.Debate
{
    public class SideSwapRequestResponse
    {
        public int SessionId { get; set; }
        public int RequesterUserId { get; set; }
        public string? RequesterName { get; set; }
        public string RequesterSide { get; set; } = null!;
        public int TargetUserId { get; set; }
        public string? TargetName { get; set; }
        public string TargetSide { get; set; } = null!;
        public DateTime CreatedAt { get; set; }
        public int ExpiresInSeconds { get; set; }
    }
}
