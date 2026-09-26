using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;
using SystemService.DAL.Entities.Debate;

namespace SystemService.DAL.Configurations.Debate
{
    public class DebateTurnConfiguration : IEntityTypeConfiguration<DebateTurn>
    {
        public void Configure(EntityTypeBuilder<DebateTurn> builder)
        {
            builder.ToTable("DebateTurns");
            builder.HasKey(e => e.TurnId);

            builder.Property(e => e.Stage).HasConversion<string>().HasMaxLength(50).IsRequired();
            builder.Property(e => e.Side).HasConversion<string>().HasMaxLength(50).IsRequired();
            builder.Property(e => e.Status).HasConversion<string>().HasMaxLength(50).IsRequired();

            builder.HasOne(e => e.Session)
                   .WithMany(s => s.Turns)
                   .HasForeignKey(e => e.SessionId)
                   .OnDelete(DeleteBehavior.Cascade);

            builder.HasIndex(e => new { e.SessionId, e.TurnOrder })
                   .IsUnique();
        }
    }
}

