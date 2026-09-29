using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;
using SystemService.DAL.Entities.Payment;

namespace SystemService.DAL.Configurations.Payment
{
    public class WalletTransactionConfiguration : IEntityTypeConfiguration<WalletTransaction>
    {
        public void Configure(EntityTypeBuilder<WalletTransaction> builder)
        {
            builder.ToTable("WalletTransactions");
            builder.HasKey(wt => wt.WalletTransactionId);

            builder.Property(wt => wt.TransactionType)
                   .HasMaxLength(20)
                   .IsRequired();

            builder.Property(wt => wt.SourceType)
                   .HasMaxLength(50)
                   .IsRequired();

            builder.Property(wt => wt.Amount)
                   .IsRequired();

            builder.Property(wt => wt.BalanceBefore)
                   .IsRequired();

            builder.Property(wt => wt.BalanceAfter)
                   .IsRequired();

            builder.Property(wt => wt.ReferenceType)
                   .HasMaxLength(50);

            builder.Property(wt => wt.Description)
                   .HasMaxLength(500);

            builder.Property(wt => wt.CreatedAt)
                   .HasDefaultValueSql("GETDATE()")
                   .IsRequired();

            builder.HasIndex(wt => wt.WalletId)
                   .HasDatabaseName("IX_WalletTransactions_Wallet");

            builder.HasIndex(wt => wt.CreatedAt)
                   .HasDatabaseName("IX_WalletTransactions_CreatedAt");

            builder.HasIndex(wt => new { wt.ReferenceType, wt.ReferenceId })
                   .HasDatabaseName("IX_WalletTransactions_Reference");

            builder.HasOne(wt => wt.Wallet)
                   .WithMany(w => w.WalletTransactions)
                   .HasForeignKey(wt => wt.WalletId)
                   .OnDelete(DeleteBehavior.Restrict);
        }
    }
}
