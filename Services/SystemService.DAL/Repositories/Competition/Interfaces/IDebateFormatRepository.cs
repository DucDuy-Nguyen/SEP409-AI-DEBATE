using System.Threading;
using System.Threading.Tasks;

namespace SystemService.DAL.Repositories.Competition.Interfaces
{
    public interface IDebateFormatRepository
    {
        Task<bool> ExistsAsync(int formatId, CancellationToken cancellationToken = default);
    }
}
