using Microsoft.EntityFrameworkCore;
using SystemService.DAL.Entities.Identity;

namespace SystemService.DAL.Context
{
    public class SystemDbContext : DbContext
    {
        public SystemDbContext(DbContextOptions<SystemDbContext> options) : base(options)
        {
        }

        public DbSet<User> Users { get; set; } = null!;
        public DbSet<Role> Roles { get; set; } = null!;
        public DbSet<UserRole> UserRoles { get; set; } = null!;
        public DbSet<OtpCode> OtpCodes { get; set; } = null!;

        public DbSet<Entities.Competition.Competition> Competitions { get; set; } = null!;
        public DbSet<Entities.Competition.CompetitionRegistration> CompetitionRegistrations { get; set; } = null!;
        public DbSet<Entities.Competition.CompetitionTeam> CompetitionTeams { get; set; } = null!;
        public DbSet<Entities.Competition.CompetitionTeamMember> CompetitionTeamMembers { get; set; } = null!;
        public DbSet<Entities.Competition.CompetitionJudge> CompetitionJudges { get; set; } = null!;
        public DbSet<Entities.Competition.DebateFormat> DebateFormats { get; set; } = null!;

        protected override void OnModelCreating(ModelBuilder modelBuilder)
        {
            base.OnModelCreating(modelBuilder);
            modelBuilder.ApplyConfigurationsFromAssembly(typeof(SystemDbContext).Assembly);
        }
    }
}
