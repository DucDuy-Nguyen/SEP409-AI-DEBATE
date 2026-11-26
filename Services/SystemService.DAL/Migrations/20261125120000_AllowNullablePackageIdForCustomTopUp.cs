using Microsoft.EntityFrameworkCore.Infrastructure;
using Microsoft.EntityFrameworkCore.Migrations;
using SystemService.DAL.Context;

#nullable disable

namespace SystemService.DAL.Migrations
{
    /// <summary>
    /// Hand-written idempotent migration allowing NULL PackageId on PaymentTransactions
    /// so custom credit top-up orders can be stored without creating synthetic CreditPackages.
    /// </summary>
    [DbContext(typeof(SystemDbContext))]
    [Migration("20261125120000_AllowNullablePackageIdForCustomTopUp")]
    public class AllowNullablePackageIdForCustomTopUp : Migration
    {
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.Sql(
                "IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.PaymentTransactions') AND name = 'PackageId' AND is_nullable = 0) " +
                "ALTER TABLE [dbo].[PaymentTransactions] ALTER COLUMN [PackageId] INT NULL;");
        }

        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.Sql(
                "IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id = OBJECT_ID('dbo.PaymentTransactions') AND name = 'PackageId' AND is_nullable = 1) " +
                "AND NOT EXISTS (SELECT 1 FROM [dbo].[PaymentTransactions] WHERE [PackageId] IS NULL) " +
                "ALTER TABLE [dbo].[PaymentTransactions] ALTER COLUMN [PackageId] INT NOT NULL;");
        }
    }
}
