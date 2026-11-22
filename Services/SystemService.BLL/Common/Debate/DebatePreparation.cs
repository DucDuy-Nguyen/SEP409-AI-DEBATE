using System;
using System.Linq;
using SystemService.DAL.Entities.Debate;
using SystemService.DAL.Entities.Debate.Enums;

namespace SystemService.BLL.Common.Debate
{
    /// <summary>
    /// Every round opens with a preparation minute: before Round 1 (the session is InProgress from the start) and
    /// between rounds. A round's DebateRound.StartTime is set 60 s ahead when it becomes the current round, and no
    /// argument is accepted before it. No column of its own: the preparation end is the start of the current round.
    /// An AI practice may skip it (POST /debate/{id}/skip-preparation).
    /// </summary>
    public static class DebatePreparation
    {
        public const int Seconds = 60;

        public static readonly string[] RoundLabels = { "Mở đầu", "Phản biện", "Kết luận" };

        /// <summary>The start of a round that becomes the current one at <paramref name="now"/>: after its preparation.</summary>
        public static DateTime RoundStart(DateTime now) => now.AddSeconds(Seconds);

        /// <summary>The round under way or in its preparation: started (StartTime set) and not ended.</summary>
        public static DebateRound? CurrentRound(DebateSession session) =>
            session.DebateRounds
                .Where(r => r.StartTime.HasValue && !r.EndTime.HasValue)
                .OrderBy(r => r.RoundNumber)
                .FirstOrDefault();

        /// <summary>When the preparation of the current round ends (its start), or null when no round is current.</summary>
        public static DateTime? EndsAt(DebateSession session)
        {
            if (session.StartTime == null || session.Status == SessionStatus.Waiting)
            {
                return null;
            }
            return AsUtc(CurrentRound(session)?.StartTime);
        }

        /// <summary>
        /// The times are stored in UTC, but SQL Server gives them back with Kind Unspecified, which JSON writes without
        /// "Z": a browser then reads them as local time (7 h off in Vietnam). Mark them UTC before they go out.
        /// </summary>
        public static DateTime? AsUtc(DateTime? value) =>
            value.HasValue ? DateTime.SpecifyKind(value.Value, DateTimeKind.Utc) : null;

        public static bool IsPreparing(DebateSession session, DateTime now)
        {
            var endsAt = EndsAt(session);
            return session.Status == SessionStatus.InProgress && endsAt.HasValue && endsAt.Value > now;
        }

        public static string RoundLabel(int roundNumber) =>
            roundNumber >= 1 && roundNumber <= RoundLabels.Length ? RoundLabels[roundNumber - 1] : $"Vòng {roundNumber}";

        public const string InProgressMessage = "Đang trong thời gian chuẩn bị, vòng tiếp theo chưa bắt đầu.";
    }
}
