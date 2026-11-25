using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using SystemService.DAL.Entities.Payment;

namespace SystemService.DAL.Repositories.Payment.Interfaces
{
    public interface IRewardRepository
    {
        Task<List<CreditRule>> GetAllRulesAsync(CancellationToken cancellationToken = default);
        Task<CreditRule?> GetRuleByCodeAsync(string ruleCode, CancellationToken cancellationToken = default);
        Task<CreditRule?> GetActiveRuleByCodeAsync(string ruleCode, CancellationToken cancellationToken = default);
        Task<bool> HasClaimedAsync(int userId, int ruleId, string claimKey, CancellationToken cancellationToken = default);
        Task<RewardClaim> CreateClaimAsync(RewardClaim claim, CancellationToken cancellationToken = default);
    }
}
