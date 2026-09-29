using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;
using SystemService.DAL.Entities.Payment;

namespace SystemService.DAL.Configurations.Payment
{
    public class PaymentTransactionConfiguration : IEntityTypeConfiguration<PaymentTransaction>
    {
        public void Configure(EntityTypeBuilder<PaymentTransaction> builder)
        {
            builder.ToTable("PaymentTransactions");
            builder.HasKey(pt => pt.PaymentId);

            builder.Property(pt => pt.Amount)
                   .HasColumnType("decimal(18,2)")
                   .IsRequired();

            builder.Property(pt => pt.Currency)
                   .HasMaxLength(10)
                   .HasDefaultValue("VND")
                   .IsRequired();

            builder.Property(pt => pt.CreditAmount)
                   .IsRequired();

            builder.Property(pt => pt.Provider)
                   .HasMaxLength(50)
                   .HasDefaultValue("PayOS")
                   .IsRequired();

            builder.Property(pt => pt.ProviderOrderCode)
                   .IsRequired();

            builder.Property(pt => pt.ProviderTransactionId)
                   .HasMaxLength(255);

            builder.Property(pt => pt.Status)
                   .HasMaxLength(30)
                   .HasDefaultValue("Pending")
                   .IsRequired();

            builder.Property(pt => pt.CreatedAt)
                   .HasDefaultValueSql("GETDATE()")
                   .IsRequired();

            builder.HasIndex(pt => new { pt.Provider, pt.ProviderOrderCode })
                   .IsUnique()
                   .HasDatabaseName("UQ_PaymentTransactions_Provider_OrderCode");

            builder.HasIndex(pt => pt.UserId)
                   .HasDatabaseName("IX_PaymentTransactions_User");

            builder.HasIndex(pt => pt.WalletId)
                   .HasDatabaseName("IX_PaymentTransactions_Wallet");

            builder.HasIndex(pt => pt.Status)
                   .HasDatabaseName("IX_PaymentTransactions_Status");

            builder.HasOne(pt => pt.User)
                   .WithMany()
                   .HasForeignKey(pt => pt.UserId)
                   .OnDelete(DeleteBehavior.Restrict);

            builder.HasOne(pt => pt.Wallet)
                   .WithMany(w => w.PaymentTransactions)
                   .HasForeignKey(pt => pt.WalletId)
                   .OnDelete(DeleteBehavior.Restrict);

            builder.HasOne(pt => pt.Package)
                   .WithMany(cp => cp.PaymentTransactions)
                   .HasForeignKey(pt => pt.PackageId)
                   .OnDelete(DeleteBehavior.Restrict);
        }
    }
}
