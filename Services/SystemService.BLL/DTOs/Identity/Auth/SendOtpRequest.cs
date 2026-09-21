using System.ComponentModel.DataAnnotations;

namespace SystemService.BLL.DTOs.Identity.Auth
{
    public class SendOtpRequest
    {
        [Required(ErrorMessage = "Email is required.")]
        [EmailAddress(ErrorMessage = "Invalid Email format.")]
        public string Email { get; set; } = null!;

        [Required(ErrorMessage = "Type is required.")]
        public string Type { get; set; } = null!;
    }
}
