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

            builder.Property(e => e.ScoreSource).HasMaxLength(10).HasDefaultValue("JUDGE").IsRequired();
            builder.Property(e => e.JudgeUserId).IsRequired(false);
            builder.Property(e => e.DebateRoundId).IsRequired(false);
            builder.Property(e => e.Score).HasPrecision(5, 2).IsRequired();
            builder.Property(e => e.CreatedAt).HasDefaultValueSql("GETDATE()");

            builder.HasIndex(e => new { e.CompetitionMatchId, e.MatchParticipantId, e.CriteriaId, e.DebateRoundId })
                .IsUnique()
                .HasFilter("[ScoreSource] = 'AI' AND [DebateRoundId] IS NOT NULL")
                .HasDatabaseName("UQ_JudgeScores_AI_PerRound");

            builder.HasIndex(e => new { e.CompetitionMatchId, e.JudgeUserId, e.MatchParticipantId, e.CriteriaId, e.DebateRoundId })
                .IsUnique()
                .HasFilter("[ScoreSource] = 'JUDGE' AND [DebateRoundId] IS NOT NULL")
                .HasDatabaseName("UQ_JudgeScores_Judge_PerRound");

            builder.HasIndex(e => new { e.CompetitionMatchId, e.JudgeUserId, e.MatchParticipantId, e.CriteriaId })
                .IsUnique()
                .HasFilter("[DebateRoundId] IS NULL")
                .HasDatabaseName("UQ_JudgeScores_Legacy_MatchLevel");

            builder.HasOne(e => e.Match)
                .WithMany(m => m.JudgeScores)
                .HasForeignKey(e => e.CompetitionMatchId)
                .OnDelete(DeleteBehavior.Restrict);

            builder.HasOne(e => e.JudgeUser)
                .WithMany()
                .HasForeignKey(e => e.JudgeUserId)
                .IsRequired(false)
                .OnDelete(DeleteBehavior.Restrict);

            builder.HasOne(e => e.Participant)
                .WithMany(p => p.JudgeScores)
                .HasForeignKey(e => e.MatchParticipantId)
                .OnDelete(DeleteBehavior.Restrict);

            builder.HasOne(e => e.Criteria)
                .WithMany(c => c.JudgeScores)
                .HasForeignKey(e => e.CriteriaId)
                .OnDelete(DeleteBehavior.Restrict);

            builder.HasOne(e => e.DebateRound)
                .WithMany()
                .HasForeignKey(e => e.DebateRoundId)
                .IsRequired(false)
                .OnDelete(DeleteBehavior.Restrict);
        }
    }
}
