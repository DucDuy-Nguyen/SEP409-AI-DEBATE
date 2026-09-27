using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;
using SystemService.DAL.Entities.Identity;

namespace SystemService.DAL.Configurations.Identity
{
    public class RefreshTokenConfiguration : IEntityTypeConfiguration<RefreshToken>
    {
        public void Configure(EntityTypeBuilder<RefreshToken> builder)
        {
            builder.ToTable("RefreshTokens");
            builder.HasKey(e => e.Id);

            builder.HasIndex(e => e.Token).IsUnique();

            builder.Property(e => e.Token).HasMaxLength(256).IsRequired();
            builder.Property(e => e.ReplacedByToken).HasMaxLength(256);
            builder.Property(e => e.IsRevoked).HasDefaultValue(false);
            builder.Property(e => e.CreatedAt).HasDefaultValueSql("GETUTCDATE()");

            builder.HasOne(e => e.User)
                   .WithMany(u => u.RefreshTokens)
                   .HasForeignKey(e => e.UserId)
                   .OnDelete(DeleteBehavior.Cascade);
        }
    }
}
