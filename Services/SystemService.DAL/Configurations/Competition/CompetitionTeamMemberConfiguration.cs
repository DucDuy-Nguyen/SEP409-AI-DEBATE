using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Metadata.Builders;
using SystemService.DAL.Entities.Competition;

namespace SystemService.DAL.Configurations.Competition
{
    public class CompetitionTeamMemberConfiguration : IEntityTypeConfiguration<CompetitionTeamMember>
    {
        public void Configure(EntityTypeBuilder<CompetitionTeamMember> builder)
        {
            builder.ToTable("CompetitionTeamMembers");
            builder.HasKey(e => e.TeamMemberId);

            builder.HasIndex(e => new { e.TeamId, e.UserId })
                .IsUnique()
                .HasDatabaseName("UQ_CompetitionTeamMembers");

            builder.Property(e => e.JoinedAt).HasDefaultValueSql("GETDATE()");

            builder.HasOne(e => e.Team)
                .WithMany(t => t.TeamMembers)
                .HasForeignKey(e => e.TeamId)
                .OnDelete(DeleteBehavior.Restrict);

            builder.HasOne(e => e.User)
                .WithMany()
                .HasForeignKey(e => e.UserId)
                .OnDelete(DeleteBehavior.Restrict);
        }
    }
}
