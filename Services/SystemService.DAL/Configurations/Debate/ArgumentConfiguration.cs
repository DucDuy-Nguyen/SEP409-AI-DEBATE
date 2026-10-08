using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;
using SystemService.DAL.Entities.Debate;

namespace SystemService.DAL.Configurations.Debate
{
    public class ArgumentConfiguration : IEntityTypeConfiguration<Argument>
    {
        public void Configure(EntityTypeBuilder<Argument> builder)
        {
            builder.ToTable("Arguments");
            builder.HasKey(e => e.ArgumentId);

            builder.Property(e => e.Content).IsRequired();

            builder.HasOne(e => e.Round)
                   .WithMany(r => r.Arguments)
                   .HasForeignKey(e => e.RoundId)
                   .OnDelete(DeleteBehavior.Cascade);

            builder.HasOne(e => e.Participant)
                   .WithMany(p => p.Arguments)
                   .HasForeignKey(e => e.ParticipantId)
                   .OnDelete(DeleteBehavior.Restrict);
        }
    }
}
