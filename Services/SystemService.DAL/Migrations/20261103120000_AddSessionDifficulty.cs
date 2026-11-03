using Microsoft.EntityFrameworkCore.Infrastructure;
using Microsoft.EntityFrameworkCore.Migrations;
using SystemService.DAL.Context;

#nullable disable

namespace SystemService.DAL.Migrations
{
    /// <summary>
    /// Written by hand, and SystemDbContextModelSnapshot is deliberately not updated: the snapshot is far behind the
    /// model, so `dotnet ef migrations add` scaffolds about 1400 lines that create and drop 20 tables with data loss.
    /// Databases here are made by EnsureCreated, which never alters an existing table and leaves no migration history,
    /// so an existing database needs the Up statement run by hand. The older migrations already create this column,
    /// hence the check.
    /// </summary>
    [DbContext(typeof(SystemDbContext))]
    [Migration("20261103120000_AddSessionDifficulty")]
    public class AddSessionDifficulty : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.Sql(
                "IF COL_LENGTH('DebateSessions', 'Difficulty') IS NULL " +
                "ALTER TABLE [DebateSessions] ADD [Difficulty] nvarchar(50) NULL;");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.Sql(
                "IF COL_LENGTH('DebateSessions', 'Difficulty') IS NOT NULL " +
                "ALTER TABLE [DebateSessions] DROP COLUMN [Difficulty];");
        }
    }
}
