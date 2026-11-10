using System.ComponentModel.DataAnnotations;
using SystemService.BLL.DTOs.AI;

namespace SystemService.BLL.DTOs.Debate
{
    public class SubmitArgumentRequest
    {
        [Required]
        public string Content { get; set; } = null!;

        public int? DurationSeconds { get; set; }

        public DeliveryAnalyticsDto? DeliveryAnalytics { get; set; }
    }
}
