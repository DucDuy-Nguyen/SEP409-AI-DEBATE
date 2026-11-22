using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace SystemService.DAL.Migrations
{
    /// <inheritdoc />
    public partial class AddRoundRubricScoresAndEvaluationStatus : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            // 1. CompetitionMatches: Add Evaluation and Finalization columns
            migrationBuilder.AddColumn<string>(
                name: "EvaluationStatus",
                table: "CompetitionMatches",
                type: "nvarchar(50)",
                maxLength: 50,
                nullable: false,
                defaultValue: "Pending");

            migrationBuilder.AddColumn<string>(
                name: "EvaluationError",
                table: "CompetitionMatches",
                type: "nvarchar(max)",
                nullable: true);

            migrationBuilder.AddColumn<DateTime>(
                name: "EvaluationStartedAt",
                table: "CompetitionMatches",
                type: "datetime2",
                nullable: true);

            migrationBuilder.AddColumn<string>(
                name: "DecisionType",
                table: "CompetitionMatches",
                type: "nvarchar(50)",
                maxLength: 50,
                nullable: true);

            migrationBuilder.AddColumn<string>(
                name: "DecisionReason",
                table: "CompetitionMatches",
                type: "nvarchar(2000)",
                maxLength: 2000,
                nullable: true);

            migrationBuilder.AddColumn<int>(
                name: "FinalizedByUserId",
                table: "CompetitionMatches",
                type: "int",
                nullable: true);

            migrationBuilder.CreateIndex(
                name: "IX_CompetitionMatches_FinalizedByUserId",
                table: "CompetitionMatches",
                column: "FinalizedByUserId");

            migrationBuilder.AddForeignKey(
                name: "FK_CompetitionMatches_FinalizedByUser",
                table: "CompetitionMatches",
                column: "FinalizedByUserId",
                principalTable: "Users",
                principalColumn: "UserId",
                onDelete: ReferentialAction.Restrict);

            // 2. DebateScoreWeight (DebateCriteria): Add CriterionCode, update MaxScore = 5.00
            migrationBuilder.AddColumn<string>(
                name: "CriterionCode",
                table: "DebateScoreWeight",
                type: "nvarchar(50)",
                maxLength: 50,
                nullable: true);

            migrationBuilder.Sql(@"
                UPDATE [dbo].[DebateScoreWeight] SET [CriterionCode] = 'LOGIC' WHERE [CriteriaName] = 'Logic';
                UPDATE [dbo].[DebateScoreWeight] SET [CriterionCode] = 'EVIDENCE' WHERE [CriteriaName] = 'Evidence';
                UPDATE [dbo].[DebateScoreWeight] SET [CriterionCode] = 'RELEVANCE' WHERE [CriteriaName] = 'Relevance';
                UPDATE [dbo].[DebateScoreWeight] SET [CriterionCode] = 'STRUCTURE' WHERE [CriteriaName] = 'Structure';
                UPDATE [dbo].[DebateScoreWeight] SET [CriterionCode] = 'PERSUASIVENESS' WHERE [CriteriaName] = 'Persuasiveness';
                UPDATE [dbo].[DebateScoreWeight] SET [CriterionCode] = UPPER(REPLACE([CriteriaName], ' ', '_')) WHERE [CriterionCode] IS NULL;
                UPDATE [dbo].[DebateScoreWeight] SET [MaxScore] = 5.00;
            ");

            migrationBuilder.AlterColumn<string>(
                name: "CriterionCode",
                table: "DebateScoreWeight",
                type: "nvarchar(50)",
                maxLength: 50,
                nullable: false);

            migrationBuilder.CreateIndex(
                name: "UQ_DebateCriteria_Code",
                table: "DebateScoreWeight",
                column: "CriterionCode",
                unique: true);

            // 3. JudgeScores: Add ScoreSource and DebateRoundId, make JudgeUserId nullable
            migrationBuilder.AddColumn<string>(
                name: "ScoreSource",
                table: "JudgeScores",
                type: "nvarchar(10)",
                maxLength: 10,
                nullable: false,
                defaultValue: "JUDGE");

            migrationBuilder.AddColumn<int>(
                name: "DebateRoundId",
                table: "JudgeScores",
                type: "int",
                nullable: true);

            migrationBuilder.AlterColumn<int>(
                name: "JudgeUserId",
                table: "JudgeScores",
                type: "int",
                nullable: true);

            migrationBuilder.CreateIndex(
                name: "IX_JudgeScores_DebateRoundId",
                table: "JudgeScores",
                column: "DebateRoundId");

            migrationBuilder.AddForeignKey(
                name: "FK_JudgeScores_DebateRounds",
                table: "JudgeScores",
                column: "DebateRoundId",
                principalTable: "DebateRounds",
                principalColumn: "RoundId",
                onDelete: ReferentialAction.Restrict);

            // Safely drop old UQ_JudgeScores constraint or index
            migrationBuilder.Sql(@"
                IF EXISTS (SELECT 1 FROM sys.key_constraints WHERE name = 'UQ_JudgeScores' AND parent_object_id = OBJECT_ID('dbo.JudgeScores'))
                BEGIN
                    ALTER TABLE [dbo].[JudgeScores] DROP CONSTRAINT [UQ_JudgeScores];
                END
                ELSE IF EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'UQ_JudgeScores' AND object_id = OBJECT_ID('dbo.JudgeScores'))
                BEGIN
                    DROP INDEX [UQ_JudgeScores] ON [dbo].[JudgeScores];
                END;
            ");

            // Add check constraints for ScoreSource and JudgeUserId
            migrationBuilder.Sql(@"
                IF NOT EXISTS (SELECT 1 FROM sys.check_constraints WHERE name = 'CK_JudgeScores_ScoreSource')
                    ALTER TABLE [dbo].[JudgeScores] ADD CONSTRAINT [CK_JudgeScores_ScoreSource] CHECK ([ScoreSource] IN ('AI', 'JUDGE'));

                IF NOT EXISTS (SELECT 1 FROM sys.check_constraints WHERE name = 'CK_JudgeScores_AI_JudgeUserId')
                    ALTER TABLE [dbo].[JudgeScores] ADD CONSTRAINT [CK_JudgeScores_AI_JudgeUserId] CHECK ([ScoreSource] <> 'AI' OR [JudgeUserId] IS NULL);

                IF NOT EXISTS (SELECT 1 FROM sys.check_constraints WHERE name = 'CK_JudgeScores_Judge_JudgeUserId')
                    ALTER TABLE [dbo].[JudgeScores] ADD CONSTRAINT [CK_JudgeScores_Judge_JudgeUserId] CHECK ([ScoreSource] <> 'JUDGE' OR [JudgeUserId] IS NOT NULL);

                IF NOT EXISTS (SELECT 1 FROM sys.check_constraints WHERE name = 'CK_JudgeScores_AI_RoundId')
                    ALTER TABLE [dbo].[JudgeScores] ADD CONSTRAINT [CK_JudgeScores_AI_RoundId] CHECK ([ScoreSource] <> 'AI' OR [DebateRoundId] IS NOT NULL);
            ");

            // Add 3 Filtered Unique Indexes
            migrationBuilder.CreateIndex(
                name: "UQ_JudgeScores_AI_PerRound",
                table: "JudgeScores",
                columns: new[] { "CompetitionMatchId", "MatchParticipantId", "CriteriaId", "DebateRoundId" },
                unique: true,
                filter: "[ScoreSource] = 'AI' AND [DebateRoundId] IS NOT NULL");

            migrationBuilder.CreateIndex(
                name: "UQ_JudgeScores_Judge_PerRound",
                table: "JudgeScores",
                columns: new[] { "CompetitionMatchId", "JudgeUserId", "MatchParticipantId", "CriteriaId", "DebateRoundId" },
                unique: true,
                filter: "[ScoreSource] = 'JUDGE' AND [DebateRoundId] IS NOT NULL");

            migrationBuilder.CreateIndex(
                name: "UQ_JudgeScores_Legacy_MatchLevel",
                table: "JudgeScores",
                columns: new[] { "CompetitionMatchId", "JudgeUserId", "MatchParticipantId", "CriteriaId" },
                unique: true,
                filter: "[DebateRoundId] IS NULL");
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            // Drop filtered indexes
            migrationBuilder.DropIndex(name: "UQ_JudgeScores_AI_PerRound", table: "JudgeScores");
            migrationBuilder.DropIndex(name: "UQ_JudgeScores_Judge_PerRound", table: "JudgeScores");
            migrationBuilder.DropIndex(name: "UQ_JudgeScores_Legacy_MatchLevel", table: "JudgeScores");

            // Drop check constraints
            migrationBuilder.Sql(@"
                IF EXISTS (SELECT 1 FROM sys.check_constraints WHERE name = 'CK_JudgeScores_ScoreSource')
                    ALTER TABLE [dbo].[JudgeScores] DROP CONSTRAINT [CK_JudgeScores_ScoreSource];
                IF EXISTS (SELECT 1 FROM sys.check_constraints WHERE name = 'CK_JudgeScores_AI_JudgeUserId')
                    ALTER TABLE [dbo].[JudgeScores] DROP CONSTRAINT [CK_JudgeScores_AI_JudgeUserId];
                IF EXISTS (SELECT 1 FROM sys.check_constraints WHERE name = 'CK_JudgeScores_Judge_JudgeUserId')
                    ALTER TABLE [dbo].[JudgeScores] DROP CONSTRAINT [CK_JudgeScores_Judge_JudgeUserId];
                IF EXISTS (SELECT 1 FROM sys.check_constraints WHERE name = 'CK_JudgeScores_AI_RoundId')
                    ALTER TABLE [dbo].[JudgeScores] DROP CONSTRAINT [CK_JudgeScores_AI_RoundId];
            ");

            // Drop JudgeScores additions
            migrationBuilder.DropForeignKey(name: "FK_JudgeScores_DebateRounds", table: "JudgeScores");
            migrationBuilder.DropIndex(name: "IX_JudgeScores_DebateRoundId", table: "JudgeScores");
            migrationBuilder.DropColumn(name: "DebateRoundId", table: "JudgeScores");
            migrationBuilder.DropColumn(name: "ScoreSource", table: "JudgeScores");

            // Drop DebateCriteria additions
            migrationBuilder.DropIndex(name: "UQ_DebateCriteria_Code", table: "DebateScoreWeight");
            migrationBuilder.DropColumn(name: "CriterionCode", table: "DebateScoreWeight");

            // Drop CompetitionMatches additions
            migrationBuilder.DropForeignKey(name: "FK_CompetitionMatches_FinalizedByUser", table: "CompetitionMatches");
            migrationBuilder.DropIndex(name: "IX_CompetitionMatches_FinalizedByUserId", table: "CompetitionMatches");
            migrationBuilder.DropColumn(name: "FinalizedByUserId", table: "CompetitionMatches");
            migrationBuilder.DropColumn(name: "DecisionReason", table: "CompetitionMatches");
            migrationBuilder.DropColumn(name: "DecisionType", table: "CompetitionMatches");
            migrationBuilder.DropColumn(name: "EvaluationStartedAt", table: "CompetitionMatches");
            migrationBuilder.DropColumn(name: "EvaluationError", table: "CompetitionMatches");
            migrationBuilder.DropColumn(name: "EvaluationStatus", table: "CompetitionMatches");
        }
    }
}
