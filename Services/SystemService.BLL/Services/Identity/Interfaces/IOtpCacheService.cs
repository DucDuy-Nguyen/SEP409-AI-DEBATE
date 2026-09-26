using System;
using System.Threading;
using System.Threading.Tasks;
using SystemService.BLL.Models.Identity;

namespace SystemService.BLL.Services.Identity.Interfaces
{
    public interface IOtpCacheService
    {
        Task SaveOtpAsync(string email, string code, string type, TimeSpan expiry, CancellationToken cancellationToken = default);
        Task<OtpCacheItem?> GetOtpAsync(string email, string type, CancellationToken cancellationToken = default);
        Task RemoveOtpAsync(string email, string type, CancellationToken cancellationToken = default);
    }
}
