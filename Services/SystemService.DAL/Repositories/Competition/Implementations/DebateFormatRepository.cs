using Microsoft.EntityFrameworkCore;
using System.Threading;
using System.Threading.Tasks;
using SystemService.DAL.Context;
using SystemService.DAL.Repositories.Competition.Interfaces;

namespace SystemService.DAL.Repositories.Competition.Implementations
{
    public class DebateFormatRepository : IDebateFormatRepository
    {
        private readonly SystemDbContext _context;

        public DebateFormatRepository(SystemDbContext context)
        {
            _context = context;
        }

        public async Task<bool> ExistsAsync(int formatId, CancellationToken cancellationToken = default)
        {
            return await _context.DebateFormats.AnyAsync(f => f.FormatId == formatId, cancellationToken);
        }
    }
}
