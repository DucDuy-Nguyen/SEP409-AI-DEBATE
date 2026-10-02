using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;
using SystemService.DAL.Entities.Debate;

namespace SystemService.DAL.Configurations.Debate
{
    public class DebateRoundConfiguration : IEntityTypeConfiguration<DebateRound>
    {
        public void Configure(EntityTypeBuilder<DebateRound> builder)
        {
            builder.ToTable("DebateRounds");
            builder.HasKey(e => e.RoundId);

            builder.Property(e => e.RoundType)
                   .HasConversion<string>()
                   .HasMaxLength(30)
                   .IsRequired();

            builder.HasOne(e => e.DebateSession)
                   .WithMany(s => s.DebateRounds)
                   .HasForeignKey(e => e.DebateSessionId)
                   .OnDelete(DeleteBehavior.Cascade);

            builder.HasIndex(e => new { e.DebateSessionId, e.RoundNumber })
                   .IsUnique();
        }
    }
}
