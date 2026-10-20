using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;
using SystemService.DAL.Entities.Competition;

namespace SystemService.DAL.Configurations.Competition
{
    public class MatchParticipantConfiguration : IEntityTypeConfiguration<MatchParticipant>
    {
        public void Configure(EntityTypeBuilder<MatchParticipant> builder)
        {
            builder.ToTable("MatchParticipants");
            builder.HasKey(e => e.MatchParticipantId);

            builder.HasIndex(e => new { e.CompetitionMatchId, e.Side })
                .IsUnique()
                .HasDatabaseName("UQ_MatchParticipants_Side");

            builder.Property(e => e.Side).HasMaxLength(10).IsRequired();
            builder.Property(e => e.FinalScore).HasPrecision(5, 2);
            builder.Property(e => e.IsWinner).HasDefaultValue(false);
            builder.Property(e => e.CreatedAt).HasDefaultValueSql("GETDATE()");

            builder.HasOne(e => e.Match)
                .WithMany(m => m.Participants)
                .HasForeignKey(e => e.CompetitionMatchId)
                .OnDelete(DeleteBehavior.Restrict);

            builder.HasOne(e => e.User)
                .WithMany()
                .HasForeignKey(e => e.UserId)
                .OnDelete(DeleteBehavior.Restrict);

            builder.HasOne(e => e.Team)
                .WithMany()
                .HasForeignKey(e => e.TeamId)
                .OnDelete(DeleteBehavior.Restrict);
        }
    }
}
