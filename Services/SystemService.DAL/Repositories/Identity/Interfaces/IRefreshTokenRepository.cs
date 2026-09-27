using System.Threading;
using System.Threading.Tasks;
using SystemService.DAL.Entities.Identity;

namespace SystemService.DAL.Repositories.Identity.Interfaces
{
    public interface IRefreshTokenRepository
    {
        Task<RefreshToken?> GetByTokenAsync(string token, CancellationToken cancellationToken = default);
        Task AddAsync(RefreshToken refreshToken, CancellationToken cancellationToken = default);
        Task UpdateAsync(RefreshToken refreshToken, CancellationToken cancellationToken = default);
        Task RevokeAllUserTokensAsync(int userId, CancellationToken cancellationToken = default);
    }
}
