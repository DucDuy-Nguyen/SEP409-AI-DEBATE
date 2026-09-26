using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;
using SystemService.DAL.Entities.Debate;

namespace SystemService.DAL.Configurations.Debate
{
    public class DebateChallengeConfiguration : IEntityTypeConfiguration<DebateChallenge>
    {
        public void Configure(EntityTypeBuilder<DebateChallenge> builder)
        {
            builder.ToTable("DebateChallenges");

            builder.HasKey(c => c.ChallengeId);

            builder.Property(c => c.Topic)
                .IsRequired()
                .HasMaxLength(500);

            builder.Property(c => c.ChallengerPreferredSide)
                .IsRequired()
                .HasConversion<string>()
                .HasMaxLength(50);

            builder.Property(c => c.Status)
                .IsRequired()
                .HasConversion<string>()
                .HasMaxLength(50);

            builder.HasOne(c => c.ChallengerUser)
                .WithMany()
                .HasForeignKey(c => c.ChallengerUserId)
                .OnDelete(DeleteBehavior.Restrict);

            builder.HasOne(c => c.ChallengedUser)
                .WithMany()
                .HasForeignKey(c => c.ChallengedUserId)
                .OnDelete(DeleteBehavior.Restrict);

            builder.HasOne(c => c.DebateSession)
                .WithMany()
                .HasForeignKey(c => c.DebateSessionId)
                .OnDelete(DeleteBehavior.SetNull);

            builder.HasIndex(c => new { c.ChallengerUserId, c.ChallengedUserId, c.Status });
        }
    }
}
