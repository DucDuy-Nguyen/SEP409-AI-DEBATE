using System;
using System.ComponentModel.DataAnnotations;

namespace IdentityService.DTOs.Users
{
    public class UpdateProfileRequest
    {
        [StringLength(150)]
        public string? FullName { get; set; }

        [StringLength(500)]
        public string? AvatarUrl { get; set; }

        public DateTime? DateOfBirth { get; set; }

        [RegularExpression("^(Male|Female|Other)$", ErrorMessage = "Gender must be Male, Female, or Other.")]
        public string? Gender { get; set; }

        [StringLength(30)]
        public string? PhoneNumber { get; set; }
    }
}
