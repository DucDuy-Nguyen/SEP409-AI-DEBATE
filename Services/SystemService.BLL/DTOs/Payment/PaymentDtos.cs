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

    public class CreditPackageAdminResponse
    {
        public int PackageId { get; set; }
        public string PackageCode { get; set; } = null!;
        public string PackageName { get; set; } = null!;
        public decimal Price { get; set; }
        public string Currency { get; set; } = "VND";
        public long CreditAmount { get; set; }
        public long BonusCredit { get; set; }
        public bool IsActive { get; set; }
        public DateTime CreatedAt { get; set; }
        public DateTime? UpdatedAt { get; set; }
    }

    public class CreateCreditPackageRequest
    {
        public string PackageCode { get; set; } = null!;
        public string PackageName { get; set; } = null!;
        public decimal Price { get; set; }
        public string Currency { get; set; } = "VND";
        public long CreditAmount { get; set; }
        public long BonusCredit { get; set; } = 0;
        public bool IsActive { get; set; } = true;
    }

    public class PatchCreditPackageRequest
    {
        private string? _packageCode;
        private bool _hasPackageCode;
        public string? PackageCode
        {
            get => _packageCode;
            set { _packageCode = value; _hasPackageCode = true; }
        }
        public bool HasPackageCode => _hasPackageCode;

        private string? _packageName;
        private bool _hasPackageName;
        public string? PackageName
        {
            get => _packageName;
            set { _packageName = value; _hasPackageName = true; }
        }
        public bool HasPackageName => _hasPackageName;

        private decimal? _price;
        private bool _hasPrice;
        public decimal? Price
        {
            get => _price;
            set { _price = value; _hasPrice = true; }
        }
        public bool HasPrice => _hasPrice;

        private string? _currency;
        private bool _hasCurrency;
        public string? Currency
        {
            get => _currency;
            set { _currency = value; _hasCurrency = true; }
        }
        public bool HasCurrency => _hasCurrency;

        private long? _creditAmount;
        private bool _hasCreditAmount;
        public long? CreditAmount
        {
            get => _creditAmount;
            set { _creditAmount = value; _hasCreditAmount = true; }
        }
        public bool HasCreditAmount => _hasCreditAmount;

        private long? _bonusCredit;
        private bool _hasBonusCredit;
        public long? BonusCredit
        {
            get => _bonusCredit;
            set { _bonusCredit = value; _hasBonusCredit = true; }
        }
        public bool HasBonusCredit => _hasBonusCredit;

        private bool? _isActive;
        private bool _hasIsActive;
        public bool? IsActive
        {
            get => _isActive;
            set { _isActive = value; _hasIsActive = true; }
        }
        public bool HasIsActive => _hasIsActive;

        public bool IsEmpty() =>
            !_hasPackageCode &&
            !_hasPackageName &&
            !_hasPrice &&
            !_hasCurrency &&
            !_hasCreditAmount &&
            !_hasBonusCredit &&
            !_hasIsActive;
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
