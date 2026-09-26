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
            builder.HasKey(e => e.SessionId);

            builder.Property(e => e.Title).HasMaxLength(200).IsRequired();
            builder.Property(e => e.Topic).HasMaxLength(500).IsRequired();
            builder.Property(e => e.Difficulty).HasMaxLength(50).IsRequired(false);

            builder.Property(e => e.DebateType).HasConversion<string>().HasMaxLength(50).IsRequired();
            builder.Property(e => e.CurrentStage).HasConversion<string>().HasMaxLength(50).IsRequired();
            builder.Property(e => e.CurrentTurnSide).HasConversion<string>().HasMaxLength(50).IsRequired();
            builder.Property(e => e.Status).HasConversion<string>().HasMaxLength(50).IsRequired();

            builder.HasOne(e => e.CreatedByUser)
                   .WithMany()
                   .HasForeignKey(e => e.CreatedByUserId)
                   .OnDelete(DeleteBehavior.Restrict);
        }
    }
}
