using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;
using SystemService.DAL.Entities.Debate;
using SystemService.DAL.Entities.Debate.Enums;

namespace SystemService.DAL.Configurations.Debate
{
    public class DebateChallengeConfiguration : IEntityTypeConfiguration<DebateChallenge>
    {
        public void Configure(EntityTypeBuilder<DebateChallenge> builder)
        {
            builder.ToTable("DebateChallenges");

            builder.HasKey(c => c.ChallengeId);

            builder.Property(c => c.TopicId)
                .IsRequired();

            builder.Property(c => c.PreferredSide)
                .IsRequired()
                .HasMaxLength(10)
                .HasConversion(
                    v => (v == DebateSide.CON || v == DebateSide.Negative) ? "CON" : "PRO",
                    v => v == "CON" ? DebateSide.CON : DebateSide.PRO
                );

            builder.Property(c => c.TurnTimeLimitSeconds)
                .IsRequired()
                .HasDefaultValue(180);

            builder.Property(c => c.Status)
                .IsRequired()
                .HasMaxLength(20)
                .HasConversion<string>();

            builder.Property(c => c.CreatedAt)
                .IsRequired();

            builder.HasOne(c => c.ChallengerUser)
                .WithMany()
                .HasForeignKey(c => c.ChallengerUserId)
                .OnDelete(DeleteBehavior.Restrict);

            builder.HasOne(c => c.ChallengedUser)
                .WithMany()
                .HasForeignKey(c => c.ChallengedUserId)
                .OnDelete(DeleteBehavior.Restrict);

            builder.HasOne(c => c.Topic)
                .WithMany()
                .HasForeignKey(c => c.TopicId)
                .OnDelete(DeleteBehavior.Restrict);

            builder.HasOne(c => c.DebateSession)
                .WithMany()
                .HasForeignKey(c => c.DebateSessionId)
                .OnDelete(DeleteBehavior.Restrict);

            // Indexes matching DB schema
            builder.HasIndex(c => c.ChallengerUserId)
                .HasDatabaseName("IX_DebateChallenges_Challenger");

            builder.HasIndex(c => c.ChallengedUserId)
                .HasDatabaseName("IX_DebateChallenges_Challenged");

            builder.HasIndex(c => c.Status)
                .HasDatabaseName("IX_DebateChallenges_Status");

            builder.HasIndex(c => c.TopicId)
                .HasDatabaseName("IX_DebateChallenges_Topic");

            builder.HasIndex(c => c.DebateSessionId)
                .HasDatabaseName("IX_DebateChallenges_DebateSession");

            builder.HasIndex(c => c.CreatedAt)
                .HasDatabaseName("IX_DebateChallenges_CreatedAt");

            builder.HasIndex(c => new { c.ChallengerUserId, c.ChallengedUserId })
                .IsUnique()
                .HasFilter("[Status] = 'Pending'")
                .HasDatabaseName("UQ_DebateChallenges_Pending");
        }
    }
}
