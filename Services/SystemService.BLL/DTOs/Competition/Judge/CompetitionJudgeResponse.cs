using System;

namespace SystemService.BLL.DTOs.Competition.Judge
{
    public class CompetitionJudgeResponse
    {
        public int CompetitionJudgeId { get; set; }
        public int CompetitionId { get; set; }
        public int UserId { get; set; }
        public string FullName { get; set; } = string.Empty;
        public string Email { get; set; } = string.Empty;
        public DateTime AssignedAt { get; set; }
    }
}
