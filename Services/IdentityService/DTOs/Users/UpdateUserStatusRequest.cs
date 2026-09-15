using System.ComponentModel.DataAnnotations;

namespace IdentityService.DTOs.Users
{
    public class UpdateUserStatusRequest
    {
        [Required]
        public bool IsActive { get; set; }
    }
}
