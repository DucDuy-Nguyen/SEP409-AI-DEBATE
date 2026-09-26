using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;
using SystemService.DAL.Entities.Debate;

namespace SystemService.DAL.Configurations.Debate
{
    public class DebateParticipantConfiguration : IEntityTypeConfiguration<DebateParticipant>
    {
        public void Configure(EntityTypeBuilder<DebateParticipant> builder)
        {
            builder.ToTable("DebateParticipants");
            builder.HasKey(e => e.ParticipantId);

            builder.Property(e => e.Side).HasConversion<string>().HasMaxLength(50).IsRequired();

            builder.HasOne(e => e.Session)
                   .WithMany(s => s.Participants)
                   .HasForeignKey(e => e.SessionId)
                   .OnDelete(DeleteBehavior.Cascade);

            builder.HasOne(e => e.User)
                   .WithMany()
                   .HasForeignKey(e => e.UserId)
                   .OnDelete(DeleteBehavior.Restrict);

            builder.HasIndex(e => new { e.SessionId, e.UserId })
                   .IsUnique()
                   .HasFilter("[UserId] IS NOT NULL");

            builder.HasIndex(e => new { e.SessionId, e.Side })
                   .IsUnique();
        }
    }
}

