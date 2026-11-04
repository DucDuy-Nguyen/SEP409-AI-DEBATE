using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;
using SystemService.DAL.Entities.Competition;

namespace SystemService.DAL.Configurations.Competition
{
    public class JudgeScoreConfiguration : IEntityTypeConfiguration<JudgeScore>
    {
        public void Configure(EntityTypeBuilder<JudgeScore> builder)
        {
            builder.ToTable("JudgeScores");
            builder.HasKey(e => e.JudgeScoreId);

            builder.HasIndex(e => new { e.CompetitionMatchId, e.JudgeUserId, e.MatchParticipantId, e.CriteriaId })
                .IsUnique()
                .HasDatabaseName("UQ_JudgeScores");

            builder.Property(e => e.Score).HasPrecision(5, 2).IsRequired();
            builder.Property(e => e.CreatedAt).HasDefaultValueSql("GETDATE()");

            builder.HasOne(e => e.Match)
                .WithMany(m => m.JudgeScores)
                .HasForeignKey(e => e.CompetitionMatchId)
                .OnDelete(DeleteBehavior.Restrict);

            builder.HasOne(e => e.JudgeUser)
                .WithMany()
                .HasForeignKey(e => e.JudgeUserId)
                .OnDelete(DeleteBehavior.Restrict);

            builder.HasOne(e => e.Participant)
                .WithMany(p => p.JudgeScores)
                .HasForeignKey(e => e.MatchParticipantId)
                .OnDelete(DeleteBehavior.Restrict);

            builder.HasOne(e => e.Criteria)
                .WithMany(c => c.JudgeScores)
                .HasForeignKey(e => e.CriteriaId)
                .OnDelete(DeleteBehavior.Restrict);
        }
    }
}
