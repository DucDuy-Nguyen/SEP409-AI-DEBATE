using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;
using SystemService.DAL.Entities.Competition;

namespace SystemService.DAL.Configurations.Competition
{
    public class CompetitionConfiguration : IEntityTypeConfiguration<Entities.Competition.Competition>
    {
        public void Configure(EntityTypeBuilder<Entities.Competition.Competition> builder)
        {
            builder.ToTable("Competitions");
            builder.HasKey(e => e.CompetitionId);

            builder.Property(e => e.Title).HasMaxLength(200).IsRequired();
            builder.Property(e => e.Description);
            builder.Property(e => e.CompetitionType).HasMaxLength(30).IsRequired();
            builder.Property(e => e.Status).HasMaxLength(30).HasDefaultValue("Draft").IsRequired();
            builder.Property(e => e.IsPublic).HasDefaultValue(true);
            builder.Property(e => e.CreatedAt).HasDefaultValueSql("GETDATE()");

            builder.HasOne(e => e.Creator)
                .WithMany()
                .HasForeignKey(e => e.CreatedBy)
                .OnDelete(DeleteBehavior.Restrict);
        }
    }
}
