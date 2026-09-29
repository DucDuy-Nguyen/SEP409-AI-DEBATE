using System;
using System.Collections.Generic;
using System.Text.Json.Serialization;
using SystemService.DAL.Entities.Identity;

namespace SystemService.DAL.Entities.Payment
{
    public class Wallet
    {
        public int WalletId { get; set; }
        public int UserId { get; set; }
        public long Balance { get; set; }
        public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
        public DateTime? UpdatedAt { get; set; }

        public User? User { get; set; }

        public ICollection<WalletTransaction> WalletTransactions { get; set; } = new List<WalletTransaction>();
        public ICollection<PaymentTransaction> PaymentTransactions { get; set; } = new List<PaymentTransaction>();
    }
}
