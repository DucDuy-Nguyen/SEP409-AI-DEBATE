using System.ComponentModel.DataAnnotations;

namespace SystemService.BLL.DTOs.Debate
{
    public class SendSwapSideRequest
    {
        [Required(ErrorMessage = "TargetUserId is required.")]
        public int TargetUserId { get; set; }
    }
}
