using System.ComponentModel.DataAnnotations;

namespace SystemService.Models.DTOs.Identity.Auth
{
    public class RegisterRequest
    {
        [Required(ErrorMessage = "Full Name is required.")]
        public string FullName { get; set; } = null!;

        [Required(ErrorMessage = "Email is required.")]
        [EmailAddress(ErrorMessage = "Invalid Email format.")]
        public string Email { get; set; } = null!;

        [Required(ErrorMessage = "Password is required.")]
        [MinLength(8, ErrorMessage = "Password must be at least 8 characters.")]
        public string Password { get; set; } = null!;
    }
}
