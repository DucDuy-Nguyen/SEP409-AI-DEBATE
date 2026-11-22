using System;
using System.ComponentModel.DataAnnotations;
using SystemService.DAL.Entities.Debate.Enums;

namespace SystemService.BLL.DTOs.Debate
{
    public class CreateChallengeRequest
    {
        [Required]
        public int ChallengedUserId { get; set; }

        // An existing topic, picked from the list. Takes priority over Topic (still required, then ignored).
        public int? TopicId { get; set; }

        [Required]
        [StringLength(500, MinimumLength = 3)]
        public string Topic { get; set; } = string.Empty;

        // Category code or Vietnamese label (see TopicCategories), required when there is no TopicId: a topic created
        // from free text must belong to a category
        [MaxLength(100)]
        public string? Category { get; set; }

        [Required]
        public DebateSide ChallengerPreferredSide { get; set; } = DebateSide.Affirmative;

        [Range(60, 600)]
        public int TurnTimeLimitSeconds { get; set; } = 180;

        public DateTime? ExpiresAt { get; set; }
    }
}
