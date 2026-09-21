using System.ComponentModel.DataAnnotations;

namespace SystemService.BLL.DTOs.Identity.Auth
{
    public class GoogleLoginRequest
    {
        [Required(ErrorMessage = "Google ID Token is required.")]
        public string IdToken { get; set; } = null!;
    }
}
