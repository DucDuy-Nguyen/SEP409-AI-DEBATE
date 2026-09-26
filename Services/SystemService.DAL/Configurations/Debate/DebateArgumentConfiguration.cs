using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;
using SystemService.DAL.Entities.Debate;

namespace SystemService.DAL.Configurations.Debate
{
    public class DebateArgumentConfiguration : IEntityTypeConfiguration<DebateArgument>
    {
        public void Configure(EntityTypeBuilder<DebateArgument> builder)
        {
            builder.ToTable("DebateArguments");
            builder.HasKey(e => e.ArgumentId);

            builder.Property(e => e.Content).IsRequired();

            builder.HasOne(e => e.Turn)
                   .WithMany(t => t.Arguments)
                   .HasForeignKey(e => e.TurnId)
                   .OnDelete(DeleteBehavior.Cascade);

            builder.HasOne(e => e.Participant)
                   .WithMany(p => p.Arguments)
                   .HasForeignKey(e => e.ParticipantId)
                   .OnDelete(DeleteBehavior.Restrict);

            builder.HasIndex(e => e.TurnId)
                   .IsUnique();
        }
    }
}

