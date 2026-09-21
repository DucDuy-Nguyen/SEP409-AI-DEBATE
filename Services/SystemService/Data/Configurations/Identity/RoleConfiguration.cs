using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;
using SystemService.Models.Entities.Identity;

namespace SystemService.Data.Configurations.Identity
{
    public class RoleConfiguration : IEntityTypeConfiguration<Role>
    {
        public void Configure(EntityTypeBuilder<Role> builder)
        {
            builder.ToTable("Roles");
            builder.HasKey(e => e.RoleId);

            builder.HasIndex(e => e.RoleName).IsUnique();

            builder.Property(e => e.RoleName).HasMaxLength(50).IsRequired();
            builder.Property(e => e.Description).HasMaxLength(255);
        }
    }
}
