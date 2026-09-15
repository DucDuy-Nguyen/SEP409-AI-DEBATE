using System;
using System.ComponentModel.DataAnnotations;

namespace IdentityService.DTOs.Auth
{
    public class RegisterRequest
    {
        [Required(ErrorMessage = "FullName is required.")]
        [StringLength(150, ErrorMessage = "FullName cannot exceed 150 characters.")]
        public string FullName { get; set; } = null!;

        [Required(ErrorMessage = "Email is required.")]
        [EmailAddress(ErrorMessage = "Invalid email address format.")]
        [StringLength(255)]
        public string Email { get; set; } = null!;

        [Required(ErrorMessage = "Password is required.")]
        [MinLength(8, ErrorMessage = "Password must be at least 8 characters.")]
        public string Password { get; set; } = null!;

        public DateTime? DateOfBirth { get; set; }

        [RegularExpression("^(Male|Female|Other)$", ErrorMessage = "Gender must be Male, Female, or Other.")]
        public string? Gender { get; set; }

        [StringLength(30)]
        public string? PhoneNumber { get; set; }
    }
}
