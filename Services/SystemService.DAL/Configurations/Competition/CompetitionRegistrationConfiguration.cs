using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;
using SystemService.DAL.Entities.Competition;

namespace SystemService.DAL.Configurations.Competition
{
    public class CompetitionRegistrationConfiguration : IEntityTypeConfiguration<CompetitionRegistration>
    {
        public void Configure(EntityTypeBuilder<CompetitionRegistration> builder)
        {
            builder.ToTable("CompetitionRegistrations");
            builder.HasKey(e => e.RegistrationId);

            builder.HasIndex(e => new { e.CompetitionId, e.UserId })
                .IsUnique()
                .HasDatabaseName("UQ_CompetitionRegistrations");

            builder.Property(e => e.Status).HasMaxLength(20).HasDefaultValue("Pending").IsRequired();
            builder.Property(e => e.Note).HasMaxLength(500);
            builder.Property(e => e.RegisteredAt).HasDefaultValueSql("GETDATE()");

            builder.HasOne(e => e.Competition)
                .WithMany(c => c.Registrations)
                .HasForeignKey(e => e.CompetitionId)
                .OnDelete(DeleteBehavior.Restrict);

            builder.HasOne(e => e.User)
                .WithMany()
                .HasForeignKey(e => e.UserId)
                .OnDelete(DeleteBehavior.Restrict);

            builder.HasOne(e => e.Reviewer)
                .WithMany()
                .HasForeignKey(e => e.ReviewedBy)
                .OnDelete(DeleteBehavior.Restrict);
        }
    }
}
