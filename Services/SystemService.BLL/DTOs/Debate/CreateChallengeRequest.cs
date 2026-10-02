using System;
using System.ComponentModel.DataAnnotations;
using SystemService.DAL.Entities.Debate.Enums;

namespace SystemService.BLL.DTOs.Debate
{
    public class CreateChallengeRequest
    {
        [Required]
        public int ChallengedUserId { get; set; }

        [Required]
        [StringLength(500, MinimumLength = 3)]
        public string Topic { get; set; } = string.Empty;

        [Required]
        public DebateSide ChallengerPreferredSide { get; set; } = DebateSide.Affirmative;

        [Range(60, 600)]
        public int TurnTimeLimitSeconds { get; set; } = 180;

        public DateTime? ExpiresAt { get; set; }
    }
}
