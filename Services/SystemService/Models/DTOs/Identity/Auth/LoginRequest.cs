using System.ComponentModel.DataAnnotations;

namespace SystemService.Models.DTOs.Identity.Auth
{
    public class LoginRequest
    {
        [Required(ErrorMessage = "Email is required.")]
        [EmailAddress(ErrorMessage = "Invalid Email format.")]
        public string Email { get; set; } = null!;

        [Required(ErrorMessage = "Password is required.")]
        public string Password { get; set; } = null!;
    }
}
