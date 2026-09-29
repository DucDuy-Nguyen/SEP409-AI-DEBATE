using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;
using SystemService.DAL.Entities.Debate;

namespace SystemService.DAL.Configurations.Debate
{
    public class TopicConfiguration : IEntityTypeConfiguration<Topic>
    {
        public void Configure(EntityTypeBuilder<Topic> builder)
        {
            builder.ToTable("Topics");
            builder.HasKey(e => e.TopicId);

            builder.Property(e => e.Title).HasMaxLength(300).IsRequired();
            builder.Property(e => e.Description).IsRequired(false);
            builder.Property(e => e.Category).HasMaxLength(100).IsRequired(false);
            builder.Property(e => e.Difficulty).HasMaxLength(20).IsRequired().HasDefaultValue("Medium");

            builder.HasOne(e => e.CreatedByUser)
                   .WithMany()
                   .HasForeignKey(e => e.CreatedBy)
                   .OnDelete(DeleteBehavior.Restrict);
        }
    }
}
