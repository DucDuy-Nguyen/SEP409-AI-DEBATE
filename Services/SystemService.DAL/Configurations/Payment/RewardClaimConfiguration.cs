using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;
using SystemService.DAL.Entities.Payment;

namespace SystemService.DAL.Configurations.Payment
{
    public class RewardClaimConfiguration : IEntityTypeConfiguration<RewardClaim>
    {
        public void Configure(EntityTypeBuilder<RewardClaim> builder)
        {
            builder.ToTable("RewardClaims");
            builder.HasKey(rc => rc.RewardClaimId);

            builder.Property(rc => rc.ClaimKey)
                   .HasMaxLength(50)
                   .IsRequired();

            builder.Property(rc => rc.ClaimedAt)
                   .HasDefaultValueSql("GETDATE()")
                   .IsRequired();

            builder.HasIndex(rc => new { rc.UserId, rc.RuleId, rc.ClaimKey })
                   .IsUnique()
                   .HasDatabaseName("UQ_RewardClaims_User_Rule_ClaimKey");

            builder.HasIndex(rc => rc.UserId)
                   .HasDatabaseName("IX_RewardClaims_User");

            builder.HasIndex(rc => rc.RuleId)
                   .HasDatabaseName("IX_RewardClaims_Rule");

            builder.HasOne(rc => rc.User)
                   .WithMany()
                   .HasForeignKey(rc => rc.UserId)
                   .OnDelete(DeleteBehavior.Restrict);

            builder.HasOne(rc => rc.Rule)
                   .WithMany(r => r.RewardClaims)
                   .HasForeignKey(rc => rc.RuleId)
                   .OnDelete(DeleteBehavior.Restrict);
        }
    }
}
