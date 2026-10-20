using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;
using SystemService.DAL.Entities.Competition;

namespace SystemService.DAL.Configurations.Competition
{
    public class CompetitionRoundConfiguration : IEntityTypeConfiguration<CompetitionRound>
    {
        public void Configure(EntityTypeBuilder<CompetitionRound> builder)
        {
            builder.ToTable("CompetitionRounds");
            builder.HasKey(e => e.CompetitionRoundId);

            builder.HasIndex(e => new { e.CompetitionId, e.RoundNumber })
                .IsUnique()
                .HasDatabaseName("UQ_CompetitionRounds");

            builder.Property(e => e.RoundNumber).IsRequired();
            builder.Property(e => e.RoundName).HasMaxLength(100).IsRequired();
            builder.Property(e => e.RoundType).HasMaxLength(30);
            builder.Property(e => e.Status).HasMaxLength(20).HasDefaultValue("Pending").IsRequired();
            builder.Property(e => e.CreatedAt).HasDefaultValueSql("GETDATE()");

            builder.HasOne(e => e.Competition)
                .WithMany(c => c.Rounds)
                .HasForeignKey(e => e.CompetitionId)
                .OnDelete(DeleteBehavior.Restrict);
        }
    }
}
