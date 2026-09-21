using System.Threading;
using System.Threading.Tasks;

namespace SystemService.BLL.Services.Identity.Interfaces
{
    public interface IEmailService
    {
        Task SendOtpEmailAsync(string toEmail, string otpCode, string purpose, CancellationToken cancellationToken = default);
    }
}
