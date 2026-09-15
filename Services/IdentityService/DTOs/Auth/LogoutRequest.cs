using System.ComponentModel.DataAnnotations;

namespace IdentityService.DTOs.Auth
{
    public class LogoutRequest
    {
        [Required(ErrorMessage = "RefreshToken is required.")]
        public string RefreshToken { get; set; } = null!;
    }
}
