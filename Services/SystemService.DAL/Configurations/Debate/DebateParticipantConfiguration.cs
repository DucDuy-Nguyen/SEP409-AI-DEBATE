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

            builder.Property(e => e.ParticipantType)
                   .HasConversion<string>()
                   .HasMaxLength(20)
                   .IsRequired();

            builder.Property(e => e.Side)
                   .HasConversion<string>()
                   .HasMaxLength(10)
                   .IsRequired();

            builder.HasOne(e => e.DebateSession)
                   .WithMany(s => s.Participants)
                   .HasForeignKey(e => e.DebateSessionId)
                   .OnDelete(DeleteBehavior.Cascade);

            builder.HasOne(e => e.User)
                   .WithMany()
                   .HasForeignKey(e => e.UserId)
                   .OnDelete(DeleteBehavior.Restrict);
        }
    }
}
