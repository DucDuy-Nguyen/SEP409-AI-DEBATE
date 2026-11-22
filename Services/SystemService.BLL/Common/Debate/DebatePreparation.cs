using System;
using System.Linq;
using SystemService.DAL.Entities.Debate;
using SystemService.DAL.Entities.Debate.Enums;

namespace SystemService.BLL.Common.Debate
{
    /// <summary>
    /// Every debate opens with a preparation minute: the session is InProgress from the start, but Round 1 only starts
    /// (DebateRound.StartTime of round 1) once it is over, and no argument is accepted before. No column of its own: the
    /// preparation end is the start of Round 1. An AI practice may skip it (POST /debate/{id}/skip-preparation).
    /// </summary>
    public static class DebatePreparation
    {
        public const int Seconds = 60;

        public static readonly string[] RoundLabels = { "Mở đầu", "Phản biện", "Kết luận" };

        /// <summary>The start of Round 1 for a debate started at <paramref name="startedAt"/>.</summary>
        public static DateTime FirstRoundStart(DateTime startedAt) => startedAt.AddSeconds(Seconds);

        /// <summary>When the preparation of a started session ends (Round 1 start), or null before it is started.</summary>
        public static DateTime? EndsAt(DebateSession session)
        {
            if (session.StartTime == null || session.Status == SessionStatus.Waiting)
            {
                return null;
            }
            return session.DebateRounds.FirstOrDefault(r => r.RoundNumber == 1)?.StartTime;
        }

        public static bool IsPreparing(DebateSession session, DateTime now)
        {
            var endsAt = EndsAt(session);
            return session.Status == SessionStatus.InProgress && endsAt.HasValue && endsAt.Value > now;
        }

        public static string RoundLabel(int roundNumber) =>
            roundNumber >= 1 && roundNumber <= RoundLabels.Length ? RoundLabels[roundNumber - 1] : $"Vòng {roundNumber}";

        public const string InProgressMessage = "Đang trong thời gian chuẩn bị, Vòng 1 chưa bắt đầu.";
    }
}
