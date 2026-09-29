using System.Threading;
using System.Threading.Tasks;
using Microsoft.EntityFrameworkCore;
using SystemService.DAL.Context;
using SystemService.DAL.Entities.Payment;
using SystemService.DAL.Repositories.Payment.Interfaces;

namespace SystemService.DAL.Repositories.Payment.Implementations
{
    public class RewardRepository : IRewardRepository
    {
        private readonly SystemDbContext _context;

        public RewardRepository(SystemDbContext context)
        {
            _context = context;
        }

        public async Task<CreditRule?> GetActiveRuleByCodeAsync(string ruleCode, CancellationToken cancellationToken = default)
        {
            return await _context.CreditRules
                .FirstOrDefaultAsync(cr => cr.RuleCode == ruleCode && cr.IsActive, cancellationToken);
        }

        public async Task<bool> HasClaimedAsync(int userId, int ruleId, string claimKey, CancellationToken cancellationToken = default)
        {
            return await _context.RewardClaims
                .AnyAsync(rc => rc.UserId == userId && rc.RuleId == ruleId && rc.ClaimKey == claimKey, cancellationToken);
        }

        public async Task<RewardClaim> CreateClaimAsync(RewardClaim claim, CancellationToken cancellationToken = default)
        {
            await _context.RewardClaims.AddAsync(claim, cancellationToken);
            await _context.SaveChangesAsync(cancellationToken);
            return claim;
        }
    }
}
