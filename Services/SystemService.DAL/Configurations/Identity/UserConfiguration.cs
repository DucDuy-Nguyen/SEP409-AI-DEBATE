using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;
using SystemService.DAL.Entities.Identity;

namespace SystemService.DAL.Configurations.Identity
{
    public class UserConfiguration : IEntityTypeConfiguration<User>
    {
        public void Configure(EntityTypeBuilder<User> builder)
        {
            builder.ToTable("Users");
            builder.HasKey(e => e.UserId);

            builder.HasIndex(e => e.Email).IsUnique();

            builder.Property(e => e.FullName).HasMaxLength(150).IsRequired();
            builder.Property(e => e.Email).HasMaxLength(255).IsRequired();
            builder.Property(e => e.PasswordHash).HasMaxLength(500).IsRequired(false);
            builder.Property(e => e.AvatarUrl).HasMaxLength(500);
            builder.Property(e => e.Gender).HasMaxLength(20);
            builder.Property(e => e.PhoneNumber).HasMaxLength(30);
            builder.Property(e => e.IsEmailVerified).HasDefaultValue(false);
            builder.Property(e => e.IsActive).HasDefaultValue(true);
        }
    }
}
