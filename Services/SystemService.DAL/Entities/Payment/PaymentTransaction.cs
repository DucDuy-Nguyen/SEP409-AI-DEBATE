using System;
using SystemService.DAL.Entities.Identity;

namespace SystemService.DAL.Entities.Payment
{
    public class PaymentTransaction
    {
        public long PaymentId { get; set; }
        public int UserId { get; set; }
        public int WalletId { get; set; }
        public int PackageId { get; set; }
        public decimal Amount { get; set; }
        public string Currency { get; set; } = "VND";
        public long CreditAmount { get; set; }
        public string Provider { get; set; } = "PayOS";
        public long ProviderOrderCode { get; set; }
        public string? ProviderTransactionId { get; set; }
        public string Status { get; set; } = "Pending";
        public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
        public DateTime? PaidAt { get; set; }
        public DateTime? CancelledAt { get; set; }
        public DateTime? ExpiredAt { get; set; }

        public User? User { get; set; }
        public Wallet? Wallet { get; set; }
        public CreditPackage? Package { get; set; }
    }
}
