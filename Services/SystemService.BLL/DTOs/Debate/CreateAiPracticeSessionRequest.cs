using System.ComponentModel.DataAnnotations;
using SystemService.DAL.Entities.Debate.Enums;

namespace SystemService.BLL.DTOs.Debate
{
    public class CreateAiPracticeSessionRequest
    {
        // An existing topic. Takes priority over Title and Topic: they are still required but then ignored.
        public int? TopicId { get; set; }

        [Required]
        [MaxLength(200)]
        public string Title { get; set; } = null!;

        [Required]
        [MaxLength(500)]
        public string Topic { get; set; } = null!;

        [Required]
        public DebateSide UserSide { get; set; } = DebateSide.Affirmative;

        public bool IsAI { get; set; } = false;

        [MaxLength(50)]
        public string? Difficulty { get; set; }

        [Range(30, 360, ErrorMessage = "Turn time limit must be between 30 and 360 seconds.")]
        public int TurnTimeLimitSeconds { get; set; } = 180;
    }
}
