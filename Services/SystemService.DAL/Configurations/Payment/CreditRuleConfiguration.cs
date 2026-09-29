using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;
using SystemService.DAL.Entities.Payment;

namespace SystemService.DAL.Configurations.Payment
{
    public class CreditRuleConfiguration : IEntityTypeConfiguration<CreditRule>
    {
        public void Configure(EntityTypeBuilder<CreditRule> builder)
        {
            builder.ToTable("CreditRules");
            builder.HasKey(cr => cr.RuleId);

            builder.Property(cr => cr.RuleCode)
                   .HasMaxLength(50)
                   .IsRequired();

            builder.Property(cr => cr.CreditAmount)
                   .IsRequired();

            builder.Property(cr => cr.Description)
                   .HasMaxLength(255);

            builder.Property(cr => cr.IsActive)
                   .HasDefaultValue(true)
                   .IsRequired();

            builder.Property(cr => cr.CreatedAt)
                   .HasDefaultValueSql("GETDATE()")
                   .IsRequired();

            builder.HasIndex(cr => cr.RuleCode)
                   .IsUnique();

            builder.HasIndex(cr => cr.IsActive)
                   .HasDatabaseName("IX_CreditRules_IsActive");
        }
    }
}
