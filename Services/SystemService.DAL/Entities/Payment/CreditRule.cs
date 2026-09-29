using System;
using System.Collections.Generic;

namespace SystemService.DAL.Entities.Payment
{
    public class CreditRule
    {
        public int RuleId { get; set; }
        public string RuleCode { get; set; } = null!;
        public long CreditAmount { get; set; }
        public string? Description { get; set; }
        public bool IsActive { get; set; } = true;
        public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
        public DateTime? UpdatedAt { get; set; }

        public ICollection<RewardClaim> RewardClaims { get; set; } = new List<RewardClaim>();
    }
}
