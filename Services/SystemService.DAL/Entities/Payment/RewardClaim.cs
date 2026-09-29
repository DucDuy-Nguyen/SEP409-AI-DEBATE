using System;
using SystemService.DAL.Entities.Identity;

namespace SystemService.DAL.Entities.Payment
{
    public class RewardClaim
    {
        public long RewardClaimId { get; set; }
        public int UserId { get; set; }
        public int RuleId { get; set; }
        public string ClaimKey { get; set; } = null!;
        public DateTime ClaimedAt { get; set; } = DateTime.UtcNow;
        public long? ReferenceId { get; set; }

        public User? User { get; set; }
        public CreditRule? Rule { get; set; }
    }
}
