using System;

namespace SystemService.BLL.DTOs.Payment
{
    public class WalletResponse
    {
        public int WalletId { get; set; }
        public long Balance { get; set; }
        public DateTime? UpdatedAt { get; set; }
    }

    public class WalletTransactionResponse
    {
        public long WalletTransactionId { get; set; }
        public string TransactionType { get; set; } = null!;
        public string SourceType { get; set; } = null!;
        public long Amount { get; set; }
        public long BalanceBefore { get; set; }
        public long BalanceAfter { get; set; }
        public string? ReferenceType { get; set; }
        public long? ReferenceId { get; set; }
        public string? Description { get; set; }
        public DateTime CreatedAt { get; set; }
    }

    public class CreditPackageResponse
    {
        public int PackageId { get; set; }
        public string PackageCode { get; set; } = null!;
        public string PackageName { get; set; } = null!;
        public decimal Price { get; set; }
        public string Currency { get; set; } = "VND";
        public long CreditAmount { get; set; }
        public long BonusCredit { get; set; }
    }

    public class TopUpRequest
    {
        public int PackageId { get; set; }
    }

    public class PaymentLinkResponse
    {
        public long PaymentId { get; set; }
        public long ProviderOrderCode { get; set; }
        public decimal Amount { get; set; }
        public string Currency { get; set; } = "VND";
        public long CreditAmount { get; set; }
        public string Provider { get; set; } = "PayOS";
        public string Status { get; set; } = "Pending";
        public string? CheckoutUrl { get; set; }
        public string? QrCode { get; set; }
    }

    public class PaymentStatusResponse
    {
        public long PaymentId { get; set; }
        public string? PackageCode { get; set; }
        public string? PackageName { get; set; }
        public decimal Amount { get; set; }
        public string Currency { get; set; } = "VND";
        public long CreditAmount { get; set; }
        public string Provider { get; set; } = "PayOS";
        public long ProviderOrderCode { get; set; }
        public string Status { get; set; } = "Pending";
        public DateTime CreatedAt { get; set; }
        public DateTime? PaidAt { get; set; }
        public DateTime? CancelledAt { get; set; }
        public DateTime? ExpiredAt { get; set; }
    }

    public class RewardStatusResponse
    {
        public bool CanClaimDailyLogin { get; set; }
        public long DailyLoginAmount { get; set; }
        public bool CanClaimFirstLogin { get; set; }
        public long FirstLoginAmount { get; set; }
    }

    public class RewardClaimResponse
    {
        public long RewardClaimId { get; set; }
        public string RuleCode { get; set; } = null!;
        public long CreditAmount { get; set; }
        public long NewBalance { get; set; }
        public DateTime ClaimedAt { get; set; }
    }
}
