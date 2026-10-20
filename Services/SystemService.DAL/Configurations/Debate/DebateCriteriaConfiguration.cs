using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;
using SystemService.DAL.Entities.Debate;

namespace SystemService.DAL.Configurations.Debate
{
    public class DebateCriteriaConfiguration : IEntityTypeConfiguration<DebateCriteria>
    {
        public void Configure(EntityTypeBuilder<DebateCriteria> builder)
        {
            builder.ToTable("DebateCriteria");
            builder.HasKey(e => e.CriteriaId);

            builder.HasIndex(e => e.CriteriaName)
                .IsUnique()
                .HasDatabaseName("UQ_DebateCriteria_Name");

            builder.Property(e => e.CriteriaName).HasMaxLength(100).IsRequired();
            builder.Property(e => e.Description).HasMaxLength(500);
            builder.Property(e => e.MaxScore).HasPrecision(5, 2).HasDefaultValue(20.0m);
            builder.Property(e => e.Weight).HasPrecision(5, 4).HasDefaultValue(1.0m);
            builder.Property(e => e.IsActive).HasDefaultValue(true);
            builder.Property(e => e.CreatedAt).HasDefaultValueSql("GETDATE()");
        }
    }
}
