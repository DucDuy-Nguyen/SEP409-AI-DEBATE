using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;
using SystemService.DAL.Entities.Debate;

namespace SystemService.DAL.Configurations.Debate
{
    public class AIJudgementConfiguration : IEntityTypeConfiguration<AIJudgement>
    {
        public void Configure(EntityTypeBuilder<AIJudgement> builder)
        {
            builder.ToTable("AIJudgements");
            builder.HasKey(e => e.JudgementId);

            builder.Property(e => e.SuggestedWinnerSide).HasMaxLength(10);
            builder.Property(e => e.OverallScorePro).HasPrecision(6, 2);
            builder.Property(e => e.OverallScoreCon).HasPrecision(6, 2);
            builder.Property(e => e.OverallScore).HasPrecision(6, 2);
            builder.Property(e => e.ConfidenceScore).HasPrecision(5, 4);
            builder.Property(e => e.AIProvider).HasMaxLength(100);
            builder.Property(e => e.AIModel).HasMaxLength(150);
            builder.Property(e => e.CreatedAt).HasDefaultValueSql("GETDATE()");

            builder.HasOne(e => e.DebateSession)
                .WithMany(s => s.AIJudgements)
                .HasForeignKey(e => e.DebateSessionId)
                .OnDelete(DeleteBehavior.Cascade);

            builder.HasOne(e => e.WinnerParticipant)
                .WithMany()
                .HasForeignKey(e => e.WinnerParticipantId)
                .OnDelete(DeleteBehavior.Restrict);
        }
    }
}
