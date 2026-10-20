using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;
using SystemService.DAL.Entities.Competition;

namespace SystemService.DAL.Configurations.Competition
{
    public class CompetitionMatchConfiguration : IEntityTypeConfiguration<CompetitionMatch>
    {
        public void Configure(EntityTypeBuilder<CompetitionMatch> builder)
        {
            builder.ToTable("CompetitionMatches");
            builder.HasKey(e => e.CompetitionMatchId);

            builder.HasIndex(e => new { e.CompetitionRoundId, e.MatchNumber })
                .IsUnique()
                .HasDatabaseName("UQ_CompetitionMatches");

            builder.Property(e => e.MatchNumber).IsRequired();
            builder.Property(e => e.BracketPosition).HasDefaultValue(1).IsRequired();
            builder.Property(e => e.Status).HasMaxLength(30).HasDefaultValue("Scheduled").IsRequired();
            builder.Property(e => e.CreatedAt).HasDefaultValueSql("GETDATE()");
            builder.Property(e => e.RowVersion).IsRowVersion();

            builder.HasOne(e => e.Competition)
                .WithMany(c => c.Matches)
                .HasForeignKey(e => e.CompetitionId)
                .OnDelete(DeleteBehavior.Restrict);

            builder.HasOne(e => e.Round)
                .WithMany(r => r.Matches)
                .HasForeignKey(e => e.CompetitionRoundId)
                .OnDelete(DeleteBehavior.Restrict);

            builder.HasOne(e => e.DebateSession)
                .WithMany()
                .HasForeignKey(e => e.DebateSessionId)
                .OnDelete(DeleteBehavior.SetNull);

            builder.HasOne(e => e.NextMatch)
                .WithMany()
                .HasForeignKey(e => e.NextMatchId)
                .OnDelete(DeleteBehavior.Restrict);

            builder.HasOne(e => e.WinnerUser)
                .WithMany()
                .HasForeignKey(e => e.WinnerUserId)
                .OnDelete(DeleteBehavior.Restrict);

            builder.HasOne(e => e.WinnerTeam)
                .WithMany()
                .HasForeignKey(e => e.WinnerTeamId)
                .OnDelete(DeleteBehavior.Restrict);

            builder.HasOne(e => e.AssignedJudgeUser)
                .WithMany()
                .HasForeignKey(e => e.AssignedJudgeUserId)
                .OnDelete(DeleteBehavior.Restrict);
        }
    }
}
