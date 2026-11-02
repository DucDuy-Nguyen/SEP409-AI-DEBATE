using SystemService.BLL.Common.Debate;
using SystemService.DAL.Entities.Debate.Enums;

namespace SystemService.Tests.Debate
{
    public class DebateTurnOrderTests
    {
        [Fact]
        public void HasSixTurnsAcrossThreeRounds()
        {
            Assert.Equal(6, DebateTurnOrder.TotalTurns);
            Assert.Equal(new[] { 0, 1, 2, 3, 4, 5 }, DebateTurnOrder.Turns.Select(t => t.TurnIndex));
            Assert.Equal(new[] { 1, 1, 2, 2, 3, 3 }, DebateTurnOrder.Turns.Select(t => t.RoundNumber));
            Assert.Equal(
                new[] { RoundType.OPENING, RoundType.OPENING, RoundType.REBUTTAL, RoundType.REBUTTAL, RoundType.CLOSING, RoundType.CLOSING },
                DebateTurnOrder.Turns.Select(t => t.RoundType));
        }

        [Fact]
        public void OpeningAndRebuttal_ProSpeaksFirst_ClosingConSpeaksFirstAndProLast()
        {
            Assert.Equal(
                new[] { DebateSide.PRO, DebateSide.CON, DebateSide.PRO, DebateSide.CON, DebateSide.CON, DebateSide.PRO },
                DebateTurnOrder.Turns.Select(t => t.Side));
        }

        [Theory]
        [InlineData(0, 1, DebateSide.PRO)]
        [InlineData(1, 1, DebateSide.CON)]
        [InlineData(2, 2, DebateSide.PRO)]
        [InlineData(3, 2, DebateSide.CON)]
        [InlineData(4, 3, DebateSide.CON)]
        [InlineData(5, 3, DebateSide.PRO)]
        public void GetNextTurn_UsesSubmittedArgumentCount(int submittedCount, int expectedRound, DebateSide expectedSide)
        {
            var next = DebateTurnOrder.GetNextTurn(submittedCount);

            Assert.NotNull(next);
            Assert.Equal(submittedCount, next!.TurnIndex);
            Assert.Equal(expectedRound, next.RoundNumber);
            Assert.Equal(expectedSide, next.Side);
            Assert.False(DebateTurnOrder.IsComplete(submittedCount));
        }

        [Theory]
        [InlineData(6)]
        [InlineData(7)]
        public void GetNextTurn_ReturnsNull_WhenAllTurnsSubmitted(int submittedCount)
        {
            Assert.Null(DebateTurnOrder.GetNextTurn(submittedCount));
            Assert.True(DebateTurnOrder.IsComplete(submittedCount));
        }

        [Theory]
        [InlineData(-1)]
        [InlineData(6)]
        public void GetTurn_OutOfRange_ReturnsNull(int turnIndex)
        {
            Assert.Null(DebateTurnOrder.GetTurn(turnIndex));
        }
    }
}
