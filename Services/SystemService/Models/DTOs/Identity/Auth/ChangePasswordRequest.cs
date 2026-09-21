using System.ComponentModel.DataAnnotations;

namespace SystemService.Models.DTOs.Identity.Auth
{
    public class ChangePasswordRequest
    {
        [Required(ErrorMessage = "Current Password is required.")]
        public string CurrentPassword { get; set; } = null!;

        [Required(ErrorMessage = "New Password is required.")]
        [MinLength(8, ErrorMessage = "New password must be at least 8 characters.")]
        public string NewPassword { get; set; } = null!;
    }
}
