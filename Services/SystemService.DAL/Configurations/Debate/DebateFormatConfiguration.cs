using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;
using SystemService.DAL.Entities.Debate;

namespace SystemService.DAL.Configurations.Debate
{
    public class DebateFormatConfiguration : IEntityTypeConfiguration<DebateFormat>
    {
        public void Configure(EntityTypeBuilder<DebateFormat> builder)
        {
            builder.ToTable("DebateFormats");
            builder.HasKey(e => e.FormatId);

            builder.Property(e => e.FormatName).HasMaxLength(100).IsRequired();
            builder.HasIndex(e => e.FormatName).IsUnique();

            builder.Property(e => e.Description).HasMaxLength(500).IsRequired(false);
        }
    }
}
