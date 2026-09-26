using Microsoft.EntityFrameworkCore;
using SystemService.DAL.Entities.Identity;
using SystemService.DAL.Entities.Debate;

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

        public DbSet<DebateSession> DebateSessions { get; set; } = null!;
        public DbSet<DebateParticipant> DebateParticipants { get; set; } = null!;
        public DbSet<DebateTurn> DebateTurns { get; set; } = null!;
        public DbSet<DebateArgument> DebateArguments { get; set; } = null!;
        public DbSet<DebateChallenge> DebateChallenges { get; set; } = null!;


        protected override void OnModelCreating(ModelBuilder modelBuilder)
        {
            base.OnModelCreating(modelBuilder);
            modelBuilder.ApplyConfigurationsFromAssembly(typeof(SystemDbContext).Assembly);
        }
    }
}

