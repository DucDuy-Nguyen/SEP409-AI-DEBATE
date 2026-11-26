using Microsoft.EntityFrameworkCore.Infrastructure;
using Microsoft.EntityFrameworkCore.Migrations;
using SystemService.DAL.Context;

#nullable disable

namespace SystemService.DAL.Migrations
{
    [DbContext(typeof(SystemDbContext))]
    [Migration("20261127000000_AddDebateSessionRoomCode")]
    public class AddDebateSessionRoomCode : Migration
    {
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.Sql(
                "IF COL_LENGTH('DebateSessions', 'RoomCode') IS NULL " +
                "ALTER TABLE [DebateSessions] ADD [RoomCode] nvarchar(16) NULL;");
            migrationBuilder.Sql(
                "IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_DebateSessions_RoomCode' AND object_id = OBJECT_ID('DebateSessions')) " +
                "CREATE UNIQUE INDEX [IX_DebateSessions_RoomCode] ON [DebateSessions] ([RoomCode]) WHERE [RoomCode] IS NOT NULL;");
        }

        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.Sql(
                "IF EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_DebateSessions_RoomCode' AND object_id = OBJECT_ID('DebateSessions')) " +
                "DROP INDEX [IX_DebateSessions_RoomCode] ON [DebateSessions];");
            migrationBuilder.Sql(
                "IF COL_LENGTH('DebateSessions', 'RoomCode') IS NOT NULL " +
                "ALTER TABLE [DebateSessions] DROP COLUMN [RoomCode];");
        }
    }
}

