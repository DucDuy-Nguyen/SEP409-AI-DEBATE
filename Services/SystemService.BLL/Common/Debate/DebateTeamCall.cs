using System;
using System.Collections.Generic;
using System.Linq;
using SystemService.BLL.DTOs.Debate;
using SystemService.DAL.Entities.Debate;
using SystemService.DAL.Entities.Debate.Enums;

namespace SystemService.BLL.Common.Debate
{
    /// <summary>
    /// Team call (2v2 rooms and team competition matches): the two human debaters of one side talk (audio, WebRTC
    /// between their browsers) during the preparation minute of each round. The server only relays the WebRTC
    /// signalling (offer / answer / ICE candidates / hangup) to the caller's human teammate, never to the other side.
    /// </summary>
    public static class DebateTeamCall
    {
        public const string Offer = "offer";
        public const string Answer = "answer";
        public const string Ice = "ice";
        public const string Hangup = "hangup";

        public static readonly IReadOnlyCollection<string> SignalTypes = new[] { Offer, Answer, Ice, Hangup };

        // An SDP offer with audio only is a few KB; ICE candidates are far smaller
        public const int MaxPayloadLength = 16 * 1024;

        public static bool IsSignalType(string? type) => type != null && SignalTypes.Contains(type);

        /// <summary>The human participants on the same side as <paramref name="userId"/>, without them.</summary>
        public static List<int> TeammateUserIds(DebateSession session, int userId)
        {
            var me = HumanParticipant(session, userId);
            if (me == null)
            {
                return new List<int>();
            }
            return session.Participants
                .Where(p => p.ParticipantType == ParticipantType.USER && p.UserId.HasValue
                    && p.UserId.Value != userId && p.Side == me.Side)
                .Select(p => p.UserId!.Value)
                .Distinct()
                .ToList();
        }

        public static DebateParticipant? HumanParticipant(DebateSession session, int userId) =>
            session.Participants.FirstOrDefault(p => p.ParticipantType == ParticipantType.USER && p.UserId == userId);

        /// <summary>A side of this session has two humans, i.e. there is somebody to call.</summary>
        public static bool HasHumanTeam(DebateSessionResponse session) =>
            session.Participants
                .Where(p => !p.IsAI && p.UserId.HasValue)
                .GroupBy(p => p.Side)
                .Any(g => g.Select(p => p.UserId).Distinct().Count() >= 2);
    }
}
