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
        public DbSet<RefreshToken> RefreshTokens { get; set; } = null!;

        public DbSet<Entities.Competition.Competition> Competitions { get; set; } = null!;
        public DbSet<Entities.Competition.CompetitionRegistration> CompetitionRegistrations { get; set; } = null!;
        public DbSet<Entities.Competition.CompetitionTeam> CompetitionTeams { get; set; } = null!;
        public DbSet<Entities.Competition.CompetitionTeamMember> CompetitionTeamMembers { get; set; } = null!;
        public DbSet<Entities.Competition.CompetitionJudge> CompetitionJudges { get; set; } = null!;
        public DbSet<Entities.Competition.CompetitionTeamRequest> CompetitionTeamRequests { get; set; } = null!;

        public DbSet<Entities.Payment.Wallet> Wallets { get; set; } = null!;
        public DbSet<Entities.Payment.WalletTransaction> WalletTransactions { get; set; } = null!;
        public DbSet<Entities.Payment.CreditPackage> CreditPackages { get; set; } = null!;
        public DbSet<Entities.Payment.PaymentTransaction> PaymentTransactions { get; set; } = null!;
        public DbSet<Entities.Payment.CreditRule> CreditRules { get; set; } = null!;
        public DbSet<Entities.Payment.RewardClaim> RewardClaims { get; set; } = null!;
        
        public DbSet<Topic> Topics { get; set; } = null!;
        public DbSet<DebateFormat> DebateFormats { get; set; } = null!;
        public DbSet<DebateSession> DebateSessions { get; set; } = null!;
        public DbSet<DebateParticipant> DebateParticipants { get; set; } = null!;
        public DbSet<DebateRound> DebateRounds { get; set; } = null!;
        public DbSet<Argument> Arguments { get; set; } = null!;
        public DbSet<DebateChallenge> DebateChallenges { get; set; } = null!;

        protected override void OnModelCreating(ModelBuilder modelBuilder)
        {
            base.OnModelCreating(modelBuilder);
            modelBuilder.ApplyConfigurationsFromAssembly(typeof(SystemDbContext).Assembly);
        }
    }
}
