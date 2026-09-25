using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;
using SystemService.DAL.Entities.Competition;

namespace SystemService.DAL.Configurations.Competition
{
    public class DebateFormatConfiguration : IEntityTypeConfiguration<DebateFormat>
    {
        public void Configure(EntityTypeBuilder<DebateFormat> builder)
        {
            builder.ToTable("DebateFormats");
            builder.HasKey(e => e.FormatId);

            builder.Property(e => e.FormatName).HasMaxLength(100).IsRequired();
            builder.Property(e => e.Description).HasMaxLength(500);
            builder.Property(e => e.MaxParticipants).HasDefaultValue(2);
            builder.Property(e => e.TotalRounds).HasDefaultValue(3);
            builder.Property(e => e.IsActive).HasDefaultValue(true);
            builder.Property(e => e.CreatedAt).HasDefaultValueSql("GETDATE()");
        }
    }
}
