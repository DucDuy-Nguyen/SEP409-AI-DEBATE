using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace SystemService.DAL.Migrations
{
    /// <inheritdoc />
    public partial class AddDebateCoreDomain : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.CreateTable(
                name: "DebateSessions",
                columns: table => new
                {
                    SessionId = table.Column<int>(type: "int", nullable: false)
                        .Annotation("SqlServer:Identity", "1, 1"),
                    Title = table.Column<string>(type: "nvarchar(200)", maxLength: 200, nullable: false),
                    Topic = table.Column<string>(type: "nvarchar(500)", maxLength: 500, nullable: false),
                    DebateType = table.Column<string>(type: "nvarchar(50)", maxLength: 50, nullable: false),
                    Difficulty = table.Column<string>(type: "nvarchar(50)", maxLength: 50, nullable: true),
                    CurrentStage = table.Column<string>(type: "nvarchar(50)", maxLength: 50, nullable: false),
                    CurrentTurnSide = table.Column<string>(type: "nvarchar(50)", maxLength: 50, nullable: false),
                    Status = table.Column<string>(type: "nvarchar(50)", maxLength: 50, nullable: false),
                    CreatedByUserId = table.Column<int>(type: "int", nullable: false),
                    CreatedAt = table.Column<DateTime>(type: "datetime2", nullable: false),
                    StartedAt = table.Column<DateTime>(type: "datetime2", nullable: true),
                    EndedAt = table.Column<DateTime>(type: "datetime2", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_DebateSessions", x => x.SessionId);
                    table.ForeignKey(
                        name: "FK_DebateSessions_Users_CreatedByUserId",
                        column: x => x.CreatedByUserId,
                        principalTable: "Users",
                        principalColumn: "UserId",
                        onDelete: ReferentialAction.Restrict);
                });

            migrationBuilder.CreateTable(
                name: "DebateParticipants",
                columns: table => new
                {
                    ParticipantId = table.Column<int>(type: "int", nullable: false)
                        .Annotation("SqlServer:Identity", "1, 1"),
                    SessionId = table.Column<int>(type: "int", nullable: false),
                    UserId = table.Column<int>(type: "int", nullable: true),
                    IsAI = table.Column<bool>(type: "bit", nullable: false),
                    Side = table.Column<string>(type: "nvarchar(50)", maxLength: 50, nullable: false),
                    JoinedAt = table.Column<DateTime>(type: "datetime2", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_DebateParticipants", x => x.ParticipantId);
                    table.ForeignKey(
                        name: "FK_DebateParticipants_DebateSessions_SessionId",
                        column: x => x.SessionId,
                        principalTable: "DebateSessions",
                        principalColumn: "SessionId",
                        onDelete: ReferentialAction.Cascade);
                    table.ForeignKey(
                        name: "FK_DebateParticipants_Users_UserId",
                        column: x => x.UserId,
                        principalTable: "Users",
                        principalColumn: "UserId",
                        onDelete: ReferentialAction.Restrict);
                });

            migrationBuilder.CreateTable(
                name: "DebateTurns",
                columns: table => new
                {
                    TurnId = table.Column<int>(type: "int", nullable: false)
                        .Annotation("SqlServer:Identity", "1, 1"),
                    SessionId = table.Column<int>(type: "int", nullable: false),
                    Stage = table.Column<string>(type: "nvarchar(50)", maxLength: 50, nullable: false),
                    Side = table.Column<string>(type: "nvarchar(50)", maxLength: 50, nullable: false),
                    TurnOrder = table.Column<int>(type: "int", nullable: false),
                    TimeLimitSeconds = table.Column<int>(type: "int", nullable: false),
                    Status = table.Column<string>(type: "nvarchar(50)", maxLength: 50, nullable: false),
                    StartedAt = table.Column<DateTime>(type: "datetime2", nullable: true),
                    EndedAt = table.Column<DateTime>(type: "datetime2", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_DebateTurns", x => x.TurnId);
                    table.ForeignKey(
                        name: "FK_DebateTurns_DebateSessions_SessionId",
                        column: x => x.SessionId,
                        principalTable: "DebateSessions",
                        principalColumn: "SessionId",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateTable(
                name: "DebateArguments",
                columns: table => new
                {
                    ArgumentId = table.Column<int>(type: "int", nullable: false)
                        .Annotation("SqlServer:Identity", "1, 1"),
                    TurnId = table.Column<int>(type: "int", nullable: false),
                    ParticipantId = table.Column<int>(type: "int", nullable: false),
                    Content = table.Column<string>(type: "nvarchar(max)", nullable: false),
                    SubmittedAt = table.Column<DateTime>(type: "datetime2", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_DebateArguments", x => x.ArgumentId);
                    table.ForeignKey(
                        name: "FK_DebateArguments_DebateParticipants_ParticipantId",
                        column: x => x.ParticipantId,
                        principalTable: "DebateParticipants",
                        principalColumn: "ParticipantId",
                        onDelete: ReferentialAction.Restrict);
                    table.ForeignKey(
                        name: "FK_DebateArguments_DebateTurns_TurnId",
                        column: x => x.TurnId,
                        principalTable: "DebateTurns",
                        principalColumn: "TurnId",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateIndex(
                name: "IX_DebateArguments_ParticipantId",
                table: "DebateArguments",
                column: "ParticipantId");

            migrationBuilder.CreateIndex(
                name: "IX_DebateArguments_TurnId",
                table: "DebateArguments",
                column: "TurnId");

            migrationBuilder.CreateIndex(
                name: "IX_DebateParticipants_SessionId",
                table: "DebateParticipants",
                column: "SessionId");

            migrationBuilder.CreateIndex(
                name: "IX_DebateParticipants_UserId",
                table: "DebateParticipants",
                column: "UserId");

            migrationBuilder.CreateIndex(
                name: "IX_DebateSessions_CreatedByUserId",
                table: "DebateSessions",
                column: "CreatedByUserId");

            migrationBuilder.CreateIndex(
                name: "IX_DebateTurns_SessionId",
                table: "DebateTurns",
                column: "SessionId");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropTable(
                name: "DebateArguments");

            migrationBuilder.DropTable(
                name: "DebateParticipants");

            migrationBuilder.DropTable(
                name: "DebateTurns");

            migrationBuilder.DropTable(
                name: "DebateSessions");
        }
    }
}
