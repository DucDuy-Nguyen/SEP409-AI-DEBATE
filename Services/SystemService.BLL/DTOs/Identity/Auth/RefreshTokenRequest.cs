using System.ComponentModel.DataAnnotations;

namespace SystemService.BLL.DTOs.Identity.Auth
{
    public class RefreshTokenRequest
    {
        [Required(ErrorMessage = "RefreshToken is required.")]
        public string RefreshToken { get; set; } = null!;
    }
}
