using Microsoft.EntityFrameworkCore.Infrastructure;
using Microsoft.EntityFrameworkCore.Migrations;
using SystemService.DAL.Context;

#nullable disable

namespace SystemService.DAL.Migrations
{
    /// <summary>
    /// Adds EnableRag column to DebateSessions table and ensures CK_Wallets_Balance_NonNegative check constraint on Wallets.
    /// Handcrafted following the pattern of AddSessionDifficulty.
    /// </summary>
    [DbContext(typeof(SystemDbContext))]
    [Migration("20261123130000_AddSessionEnableRag")]
    public class AddSessionEnableRag : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.Sql(
                "IF COL_LENGTH('DebateSessions', 'EnableRag') IS NULL " +
                "ALTER TABLE [DebateSessions] ADD [EnableRag] bit NULL CONSTRAINT DF_DebateSessions_EnableRag DEFAULT 1;");

            migrationBuilder.Sql(
                "IF NOT EXISTS (SELECT 1 FROM sys.check_constraints WHERE name = 'CK_Wallets_Balance_NonNegative') " +
                "ALTER TABLE [Wallets] ADD CONSTRAINT CK_Wallets_Balance_NonNegative CHECK ([Balance] >= 0);");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.Sql(
                "IF EXISTS (SELECT 1 FROM sys.check_constraints WHERE name = 'CK_Wallets_Balance_NonNegative') " +
                "ALTER TABLE [Wallets] DROP CONSTRAINT CK_Wallets_Balance_NonNegative;");

            migrationBuilder.Sql(
                "IF COL_LENGTH('DebateSessions', 'EnableRag') IS NOT NULL " +
                "ALTER TABLE [DebateSessions] DROP COLUMN [EnableRag];");
        }
    }
}
