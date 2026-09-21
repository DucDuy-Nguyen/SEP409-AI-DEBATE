using System.Threading;
using System.Threading.Tasks;
using SystemService.DAL.Entities.Identity;

namespace SystemService.DAL.Repositories.Identity.Interfaces
{
    public interface IOtpRepository
    {
        Task AddAsync(OtpCode otpCode, CancellationToken cancellationToken = default);
        Task<OtpCode?> GetLatestValidOtpAsync(string email, string code, string type, CancellationToken cancellationToken = default);
        Task MarkAsUsedAsync(OtpCode otpCode, CancellationToken cancellationToken = default);
        Task InvalidatePreviousOtpsAsync(string email, string type, CancellationToken cancellationToken = default);
    }
}
