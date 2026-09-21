using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;
using SystemService.DAL.Entities.Identity;

namespace SystemService.DAL.Configurations.Identity
{
    public class OtpCodeConfiguration : IEntityTypeConfiguration<OtpCode>
    {
        public void Configure(EntityTypeBuilder<OtpCode> builder)
        {
            builder.ToTable("OtpCodes");
            builder.HasKey(e => e.Id);

            builder.Property(e => e.Email).HasMaxLength(255).IsRequired();
            builder.Property(e => e.Code).HasMaxLength(10).IsRequired();
            builder.Property(e => e.Type).HasMaxLength(50).IsRequired();
            builder.Property(e => e.IsUsed).HasDefaultValue(false);

            builder.HasIndex(e => new { e.Email, e.Type, e.IsUsed });
        }
    }
}
