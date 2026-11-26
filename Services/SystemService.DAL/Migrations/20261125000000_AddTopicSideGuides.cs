using Microsoft.EntityFrameworkCore.Infrastructure;
using Microsoft.EntityFrameworkCore.Migrations;
using SystemService.DAL.Context;

#nullable disable

namespace SystemService.DAL.Migrations
{
    /// <summary>
    /// Written by hand like AddSessionDifficulty (the snapshot is far behind the model and is not updated): an
    /// existing database needs these statements run by hand, hence the checks.
    /// </summary>
    [DbContext(typeof(SystemDbContext))]
    [Migration("20261125000000_AddTopicSideGuides")]
    public class AddTopicSideGuides : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.Sql(
                "IF COL_LENGTH('Topics', 'ProGuide') IS NULL " +
                "ALTER TABLE [Topics] ADD [ProGuide] nvarchar(1000) NULL;");
            migrationBuilder.Sql(
                "IF COL_LENGTH('Topics', 'ConGuide') IS NULL " +
                "ALTER TABLE [Topics] ADD [ConGuide] nvarchar(1000) NULL;");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.Sql(
                "IF COL_LENGTH('Topics', 'ProGuide') IS NOT NULL " +
                "ALTER TABLE [Topics] DROP COLUMN [ProGuide];");
            migrationBuilder.Sql(
                "IF COL_LENGTH('Topics', 'ConGuide') IS NOT NULL " +
                "ALTER TABLE [Topics] DROP COLUMN [ConGuide];");
        }
    }
}
