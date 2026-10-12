using System.ComponentModel.DataAnnotations;

namespace SystemService.BLL.DTOs.Debate
{
    public class RespondSwapSideRequest
    {
        [Required(ErrorMessage = "RequesterUserId is required.")]
        public int RequesterUserId { get; set; }

        public bool Accept { get; set; }
    }
}
