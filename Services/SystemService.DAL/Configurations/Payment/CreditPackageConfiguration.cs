using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;
using SystemService.DAL.Entities.Payment;

namespace SystemService.DAL.Configurations.Payment
{
    public class CreditPackageConfiguration : IEntityTypeConfiguration<CreditPackage>
    {
        public void Configure(EntityTypeBuilder<CreditPackage> builder)
        {
            builder.ToTable("CreditPackages");
            builder.HasKey(cp => cp.PackageId);

            builder.Property(cp => cp.PackageCode)
                   .HasMaxLength(50)
                   .IsRequired();

            builder.Property(cp => cp.PackageName)
                   .HasMaxLength(100)
                   .IsRequired();

            builder.Property(cp => cp.Price)
                   .HasColumnType("decimal(18,2)")
                   .IsRequired();

            builder.Property(cp => cp.Currency)
                   .HasMaxLength(10)
                   .HasDefaultValue("VND")
                   .IsRequired();

            builder.Property(cp => cp.CreditAmount)
                   .IsRequired();

            builder.Property(cp => cp.BonusCredit)
                   .HasDefaultValue(0L)
                   .IsRequired();

            builder.Property(cp => cp.IsActive)
                   .HasDefaultValue(true)
                   .IsRequired();

            builder.Property(cp => cp.CreatedAt)
                   .HasDefaultValueSql("GETDATE()")
                   .IsRequired();

            builder.HasIndex(cp => cp.PackageCode)
                   .IsUnique();

            builder.HasIndex(cp => cp.IsActive)
                   .HasDatabaseName("IX_CreditPackages_IsActive");
        }
    }
}
