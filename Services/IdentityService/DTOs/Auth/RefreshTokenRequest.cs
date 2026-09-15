using System.ComponentModel.DataAnnotations;

namespace IdentityService.DTOs.Auth
{
    public class RefreshTokenRequest
    {
        [Required(ErrorMessage = "RefreshToken is required.")]
        public string RefreshToken { get; set; } = null!;
    }
}
