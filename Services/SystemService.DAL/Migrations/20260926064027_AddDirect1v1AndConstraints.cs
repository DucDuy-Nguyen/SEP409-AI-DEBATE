using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace SystemService.DAL.Migrations
{
    /// <inheritdoc />
    public partial class AddDirect1v1AndConstraints : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropIndex(
                name: "IX_DebateTurns_SessionId",
                table: "DebateTurns");

            migrationBuilder.DropIndex(
                name: "IX_DebateParticipants_SessionId",
                table: "DebateParticipants");

            migrationBuilder.DropIndex(
                name: "IX_DebateArguments_TurnId",
                table: "DebateArguments");

            migrationBuilder.CreateTable(
                name: "DebateChallenges",
                columns: table => new
                {
                    ChallengeId = table.Column<int>(type: "int", nullable: false)
                        .Annotation("SqlServer:Identity", "1, 1"),
                    ChallengerUserId = table.Column<int>(type: "int", nullable: false),
                    ChallengedUserId = table.Column<int>(type: "int", nullable: false),
                    Topic = table.Column<string>(type: "nvarchar(500)", maxLength: 500, nullable: false),
                    ChallengerPreferredSide = table.Column<string>(type: "nvarchar(50)", maxLength: 50, nullable: false),
                    TurnTimeLimitSeconds = table.Column<int>(type: "int", nullable: false),
                    Status = table.Column<string>(type: "nvarchar(50)", maxLength: 50, nullable: false),
                    DebateSessionId = table.Column<int>(type: "int", nullable: true),
                    CreatedAt = table.Column<DateTime>(type: "datetime2", nullable: false),
                    RespondedAt = table.Column<DateTime>(type: "datetime2", nullable: true),
                    ExpiresAt = table.Column<DateTime>(type: "datetime2", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_DebateChallenges", x => x.ChallengeId);
                    table.ForeignKey(
                        name: "FK_DebateChallenges_DebateSessions_DebateSessionId",
                        column: x => x.DebateSessionId,
                        principalTable: "DebateSessions",
                        principalColumn: "SessionId",
                        onDelete: ReferentialAction.SetNull);
                    table.ForeignKey(
                        name: "FK_DebateChallenges_Users_ChallengedUserId",
                        column: x => x.ChallengedUserId,
                        principalTable: "Users",
                        principalColumn: "UserId",
                        onDelete: ReferentialAction.Restrict);
                    table.ForeignKey(
                        name: "FK_DebateChallenges_Users_ChallengerUserId",
                        column: x => x.ChallengerUserId,
                        principalTable: "Users",
                        principalColumn: "UserId",
                        onDelete: ReferentialAction.Restrict);
                });

            migrationBuilder.CreateIndex(
                name: "IX_DebateTurns_SessionId_TurnOrder",
                table: "DebateTurns",
                columns: new[] { "SessionId", "TurnOrder" },
                unique: true);

            migrationBuilder.CreateIndex(
                name: "IX_DebateParticipants_SessionId_Side",
                table: "DebateParticipants",
                columns: new[] { "SessionId", "Side" },
                unique: true);

            migrationBuilder.CreateIndex(
                name: "IX_DebateParticipants_SessionId_UserId",
                table: "DebateParticipants",
                columns: new[] { "SessionId", "UserId" },
                unique: true,
                filter: "[UserId] IS NOT NULL");

            migrationBuilder.CreateIndex(
                name: "IX_DebateArguments_TurnId",
                table: "DebateArguments",
                column: "TurnId",
                unique: true);

            migrationBuilder.CreateIndex(
                name: "IX_DebateChallenges_ChallengedUserId",
                table: "DebateChallenges",
                column: "ChallengedUserId");

            migrationBuilder.CreateIndex(
                name: "IX_DebateChallenges_ChallengerUserId_ChallengedUserId_Status",
                table: "DebateChallenges",
                columns: new[] { "ChallengerUserId", "ChallengedUserId", "Status" });

            migrationBuilder.CreateIndex(
                name: "IX_DebateChallenges_DebateSessionId",
                table: "DebateChallenges",
                column: "DebateSessionId");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropTable(
                name: "DebateChallenges");

            migrationBuilder.DropIndex(
                name: "IX_DebateTurns_SessionId_TurnOrder",
                table: "DebateTurns");

            migrationBuilder.DropIndex(
                name: "IX_DebateParticipants_SessionId_Side",
                table: "DebateParticipants");

            migrationBuilder.DropIndex(
                name: "IX_DebateParticipants_SessionId_UserId",
                table: "DebateParticipants");

            migrationBuilder.DropIndex(
                name: "IX_DebateArguments_TurnId",
                table: "DebateArguments");

            migrationBuilder.CreateIndex(
                name: "IX_DebateTurns_SessionId",
                table: "DebateTurns",
                column: "SessionId");

            migrationBuilder.CreateIndex(
                name: "IX_DebateParticipants_SessionId",
                table: "DebateParticipants",
                column: "SessionId");

            migrationBuilder.CreateIndex(
                name: "IX_DebateArguments_TurnId",
                table: "DebateArguments",
                column: "TurnId");
        }
    }
}
