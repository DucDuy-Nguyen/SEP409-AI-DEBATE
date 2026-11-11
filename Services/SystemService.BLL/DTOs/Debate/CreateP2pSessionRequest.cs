using System.ComponentModel.DataAnnotations;
using SystemService.DAL.Entities.Debate.Enums;

namespace SystemService.BLL.DTOs.Debate
{
    public class CreateP2pSessionRequest
    {
        // An existing topic (its Category enables the evidence check). Takes priority over Title and Topic: they are
        // still required but then ignored. Without it the topic is found or created by its text, without a category.
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

        [Range(30, 360, ErrorMessage = "Turn time limit must be between 30 and 360 seconds.")]
        public int TurnTimeLimitSeconds { get; set; } = 180;
    }
}
