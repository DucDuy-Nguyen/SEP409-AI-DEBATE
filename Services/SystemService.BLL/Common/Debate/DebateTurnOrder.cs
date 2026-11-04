using System.Collections.Generic;
using SystemService.DAL.Entities.Debate.Enums;

namespace SystemService.BLL.Common.Debate
{
    public sealed record DebateTurnSlot(int TurnIndex, int RoundNumber, RoundType RoundType, DebateSide Side);

    /// <summary>
    /// Single source of truth for the 1v1 turn order (3 rounds x 2 turns).
    /// Opening and Rebuttal: PRO then CON. Closing is reversed: CON then PRO, so PRO speaks last.
    /// Must stay in sync with the AI Opponent service (app/opponent/match_format.py, turn_index = TurnIndex + 1).
    /// </summary>
    public static class DebateTurnOrder
    {
        public static readonly IReadOnlyList<DebateTurnSlot> Turns = new[]
        {
            new DebateTurnSlot(0, 1, RoundType.OPENING, DebateSide.PRO),
            new DebateTurnSlot(1, 1, RoundType.OPENING, DebateSide.CON),
            new DebateTurnSlot(2, 2, RoundType.REBUTTAL, DebateSide.PRO),
            new DebateTurnSlot(3, 2, RoundType.REBUTTAL, DebateSide.CON),
            new DebateTurnSlot(4, 3, RoundType.CLOSING, DebateSide.CON),
            new DebateTurnSlot(5, 3, RoundType.CLOSING, DebateSide.PRO)
        };

        public static int TotalTurns => Turns.Count;

        public static DebateTurnSlot? GetTurn(int turnIndex)
        {
            return turnIndex >= 0 && turnIndex < Turns.Count ? Turns[turnIndex] : null;
        }

        /// <summary>
        /// Next turn to be played given how many arguments the session already has; null once all turns are done.
        /// </summary>
        public static DebateTurnSlot? GetNextTurn(int submittedArgumentCount)
        {
            return GetTurn(submittedArgumentCount);
        }

        public static bool IsComplete(int submittedArgumentCount)
        {
            return submittedArgumentCount >= TotalTurns;
        }
    }
}
