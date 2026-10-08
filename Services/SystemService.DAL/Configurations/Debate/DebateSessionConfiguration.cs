using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;
using SystemService.DAL.Entities.Debate;

namespace SystemService.DAL.Configurations.Debate
{
    public class DebateSessionConfiguration : IEntityTypeConfiguration<DebateSession>
    {
        public void Configure(EntityTypeBuilder<DebateSession> builder)
        {
            builder.ToTable("DebateSessions");
            builder.HasKey(e => e.DebateSessionId);

            builder.Property(e => e.Status)
                   .HasConversion<string>()
                   .HasMaxLength(30)
                   .IsRequired();

            builder.Ignore(e => e.TurnTimeLimitSeconds);

            builder.HasOne(e => e.Topic)
                   .WithMany(t => t.DebateSessions)
                   .HasForeignKey(e => e.TopicId)
                   .OnDelete(DeleteBehavior.Restrict);

            builder.HasOne(e => e.Format)
                   .WithMany(f => f.DebateSessions)
                   .HasForeignKey(e => e.FormatId)
                   .OnDelete(DeleteBehavior.Restrict);

            builder.HasOne(e => e.CreatedByUser)
                   .WithMany()
                   .HasForeignKey(e => e.CreatedBy)
                   .OnDelete(DeleteBehavior.Restrict);
        }
    }
}
