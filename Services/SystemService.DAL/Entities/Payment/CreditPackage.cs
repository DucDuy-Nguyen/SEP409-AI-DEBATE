using System;
using System.Collections.Generic;

namespace SystemService.DAL.Entities.Payment
{
    public class CreditPackage
    {
        public int PackageId { get; set; }
        public string PackageCode { get; set; } = null!;
        public string PackageName { get; set; } = null!;
        public decimal Price { get; set; }
        public string Currency { get; set; } = "VND";
        public long CreditAmount { get; set; }
        public long BonusCredit { get; set; }
        public bool IsActive { get; set; } = true;
        public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
        public DateTime? UpdatedAt { get; set; }

        public ICollection<PaymentTransaction> PaymentTransactions { get; set; } = new List<PaymentTransaction>();
    }
}
