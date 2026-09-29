using System;

namespace SystemService.DAL.Entities.Payment
{
    public class WalletTransaction
    {
        public long WalletTransactionId { get; set; }
        public int WalletId { get; set; }
        public string TransactionType { get; set; } = null!;
        public string SourceType { get; set; } = null!;
        public long Amount { get; set; }
        public long BalanceBefore { get; set; }
        public long BalanceAfter { get; set; }
        public string? ReferenceType { get; set; }
        public long? ReferenceId { get; set; }
        public string? Description { get; set; }
        public DateTime CreatedAt { get; set; } = DateTime.UtcNow;

        public Wallet? Wallet { get; set; }
    }
}
