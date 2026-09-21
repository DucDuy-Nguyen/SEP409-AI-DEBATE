using System;
using System.ComponentModel.DataAnnotations;

namespace SystemService.BLL.DTOs.Identity.Users
{
    public class UpdateProfileRequest
    {
        [Required(ErrorMessage = "Full Name is required.")]
        public string FullName { get; set; } = null!;

        public string? AvatarUrl { get; set; }
        public DateTime? DateOfBirth { get; set; }
        public string? Gender { get; set; }
        public string? PhoneNumber { get; set; }
    }
}
