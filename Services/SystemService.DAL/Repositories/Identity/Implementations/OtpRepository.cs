using Microsoft.EntityFrameworkCore;
using System;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using SystemService.DAL.Context;
using SystemService.DAL.Entities.Identity;
using SystemService.DAL.Repositories.Identity.Interfaces;

namespace SystemService.DAL.Repositories.Identity.Implementations
{
    public class OtpRepository : IOtpRepository
    {
        private readonly SystemDbContext _context;

        public OtpRepository(SystemDbContext context)
        {
            _context = context;
        }

        public async Task AddAsync(OtpCode otpCode, CancellationToken cancellationToken = default)
        {
            await _context.OtpCodes.AddAsync(otpCode, cancellationToken);
            await _context.SaveChangesAsync(cancellationToken);
        }

        public async Task<OtpCode?> GetLatestValidOtpAsync(string email, string code, string type, CancellationToken cancellationToken = default)
        {
            var normalizedEmail = email.Trim().ToLowerInvariant();
            var now = DateTime.UtcNow;

            return await _context.OtpCodes
                .Where(o => o.Email.ToLower() == normalizedEmail 
                         && o.Code == code 
                         && o.Type == type 
                         && !o.IsUsed 
                         && o.ExpiresAt > now)
                .OrderByDescending(o => o.CreatedAt)
                .FirstOrDefaultAsync(cancellationToken);
        }

        public async Task MarkAsUsedAsync(OtpCode otpCode, CancellationToken cancellationToken = default)
        {
            otpCode.IsUsed = true;
            _context.OtpCodes.Update(otpCode);
            await _context.SaveChangesAsync(cancellationToken);
        }

        public async Task InvalidatePreviousOtpsAsync(string email, string type, CancellationToken cancellationToken = default)
        {
            var normalizedEmail = email.Trim().ToLowerInvariant();
            var previousOtps = await _context.OtpCodes
                .Where(o => o.Email.ToLower() == normalizedEmail && o.Type == type && !o.IsUsed)
                .ToListAsync(cancellationToken);

            foreach (var otp in previousOtps)
            {
                otp.IsUsed = true;
            }

            if (previousOtps.Any())
            {
                _context.OtpCodes.UpdateRange(previousOtps);
                await _context.SaveChangesAsync(cancellationToken);
            }
        }
    }
}
