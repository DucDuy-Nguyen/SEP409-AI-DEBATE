using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;
using SystemService.DAL.Entities.Competition;

namespace SystemService.DAL.Configurations.Competition
{
    public class CompetitionTeamRequestConfiguration : IEntityTypeConfiguration<CompetitionTeamRequest>
    {
        public void Configure(EntityTypeBuilder<CompetitionTeamRequest> builder)
        {
            builder.ToTable("CompetitionTeamRequests");
            builder.HasKey(e => e.RequestId);

            builder.Property(e => e.RequestType).HasMaxLength(20).IsRequired();
            builder.Property(e => e.Status).HasMaxLength(20).HasDefaultValue("Pending").IsRequired();
            builder.Property(e => e.Note).HasMaxLength(500);
            builder.Property(e => e.CreatedAt).HasDefaultValueSql("GETDATE()");

            builder.HasOne(e => e.Team)
                .WithMany()
                .HasForeignKey(e => e.TeamId)
                .OnDelete(DeleteBehavior.Restrict);

            builder.HasOne(e => e.User)
                .WithMany()
                .HasForeignKey(e => e.UserId)
                .OnDelete(DeleteBehavior.Restrict);

            builder.HasOne(e => e.Creator)
                .WithMany()
                .HasForeignKey(e => e.CreatedByUserId)
                .OnDelete(DeleteBehavior.Restrict);

            builder.HasOne(e => e.Responder)
                .WithMany()
                .HasForeignKey(e => e.RespondedByUserId)
                .OnDelete(DeleteBehavior.Restrict);
        }
    }
}
