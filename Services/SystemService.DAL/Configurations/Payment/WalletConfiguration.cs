using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;
using SystemService.DAL.Entities.Payment;

namespace SystemService.DAL.Configurations.Payment
{
    public class WalletConfiguration : IEntityTypeConfiguration<Wallet>
    {
        public void Configure(EntityTypeBuilder<Wallet> builder)
        {
            builder.ToTable("Wallets");
            builder.HasKey(w => w.WalletId);

            builder.Property(w => w.Balance)
                   .HasDefaultValue(0L)
                   .IsRequired();

            builder.Property(w => w.CreatedAt)
                   .HasDefaultValueSql("GETDATE()")
                   .IsRequired();

            builder.HasIndex(w => w.UserId)
                   .IsUnique();

            builder.HasOne(w => w.User)
                   .WithOne()
                   .HasForeignKey<Wallet>(w => w.UserId)
                   .OnDelete(DeleteBehavior.Restrict);
        }
    }
}
