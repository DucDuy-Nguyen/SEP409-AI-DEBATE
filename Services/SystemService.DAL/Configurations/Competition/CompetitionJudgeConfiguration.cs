using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;
using SystemService.DAL.Entities.Competition;

namespace SystemService.DAL.Configurations.Competition
{
    public class CompetitionJudgeConfiguration : IEntityTypeConfiguration<CompetitionJudge>
    {
        public void Configure(EntityTypeBuilder<CompetitionJudge> builder)
        {
            builder.ToTable("CompetitionJudges");
            builder.HasKey(e => e.CompetitionJudgeId);

            builder.HasIndex(e => new { e.CompetitionId, e.UserId })
                .IsUnique()
                .HasDatabaseName("UQ_CompetitionJudges");

            builder.Property(e => e.AssignedAt).HasDefaultValueSql("GETDATE()");

            builder.HasOne(e => e.Competition)
                .WithMany(c => c.Judges)
                .HasForeignKey(e => e.CompetitionId)
                .OnDelete(DeleteBehavior.Restrict);

            builder.HasOne(e => e.User)
                .WithMany()
                .HasForeignKey(e => e.UserId)
                .OnDelete(DeleteBehavior.Restrict);
        }
    }
}
