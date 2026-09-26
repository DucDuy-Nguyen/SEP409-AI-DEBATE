using System.ComponentModel.DataAnnotations;

namespace SystemService.BLL.DTOs.Debate
{
    public class SubmitArgumentRequest
    {
        [Required]
        public string Content { get; set; } = null!;
    }
}
