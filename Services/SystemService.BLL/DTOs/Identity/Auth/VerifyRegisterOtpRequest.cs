using System.ComponentModel.DataAnnotations;

namespace SystemService.BLL.DTOs.Identity.Auth
{
    public class VerifyRegisterOtpRequest
    {
        [Required(ErrorMessage = "Email is required.")]
        [EmailAddress(ErrorMessage = "Invalid Email format.")]
        public string Email { get; set; } = null!;

        [Required(ErrorMessage = "OTP code is required.")]
        public string OtpCode { get; set; } = null!;
    }
}
