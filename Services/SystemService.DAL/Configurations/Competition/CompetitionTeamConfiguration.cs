using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;
using SystemService.DAL.Entities.Competition;

namespace SystemService.DAL.Configurations.Competition
{
    public class CompetitionTeamConfiguration : IEntityTypeConfiguration<CompetitionTeam>
    {
        public void Configure(EntityTypeBuilder<CompetitionTeam> builder)
        {
            builder.ToTable("CompetitionTeams");
            builder.HasKey(e => e.TeamId);

            builder.HasIndex(e => new { e.CompetitionId, e.TeamName })
                .IsUnique()
                .HasDatabaseName("UQ_CompetitionTeams_Name");

            builder.Property(e => e.TeamName).HasMaxLength(150).IsRequired();
            builder.Property(e => e.Status).HasMaxLength(20).HasDefaultValue("Active").IsRequired();
            builder.Property(e => e.CreatedAt).HasDefaultValueSql("GETDATE()");

            builder.HasOne(e => e.Competition)
                .WithMany(c => c.Teams)
                .HasForeignKey(e => e.CompetitionId)
                .OnDelete(DeleteBehavior.Restrict);

            builder.HasOne(e => e.Captain)
                .WithMany()
                .HasForeignKey(e => e.CaptainUserId)
                .OnDelete(DeleteBehavior.Restrict);
        }
    }
}
