using System.ComponentModel.DataAnnotations;
using SystemService.DAL.Entities.Debate.Enums;

namespace SystemService.BLL.DTOs.Debate
{
    public class CreateP2pSessionRequest
    {
        [Required]
        [MaxLength(200)]
        public string Title { get; set; } = null!;

        [Required]
        [MaxLength(500)]
        public string Topic { get; set; } = null!;

        [Required]
        public DebateSide UserSide { get; set; } = DebateSide.Affirmative;

        public int TurnTimeLimitSeconds { get; set; } = 180;
    }
}
