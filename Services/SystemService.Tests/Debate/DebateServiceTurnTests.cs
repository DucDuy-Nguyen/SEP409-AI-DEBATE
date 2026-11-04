using SystemService.BLL.Common.Debate;
using SystemService.DAL.Entities.Debate.Enums;
using static SystemService.Tests.Debate.DebateTestHarness;

namespace SystemService.Tests.Debate
{
    public class DebateServiceTurnTests : IDisposable
    {
        private readonly DebateTestHarness _harness = new();

        public void Dispose() => _harness.Dispose();

        [Fact]
        public async Task AiSession_UserPro_FullFlow_ClosingAiSpeaksBeforeUser()
        {
            int sessionId = await _harness.StartAiSessionAsync(DebateSide.PRO);

            ApiResponseAssert.Succeeds(await _harness.UserSubmitsAsync(UserA, sessionId));   // 0 opening PRO
            ApiResponseAssert.Succeeds(await _harness.AiSubmitsAsync(sessionId, 1));           // 1 opening CON
            ApiResponseAssert.Succeeds(await _harness.UserSubmitsAsync(UserA, sessionId));   // 2 rebuttal PRO
            ApiResponseAssert.Succeeds(await _harness.AiSubmitsAsync(sessionId, 3));           // 3 rebuttal CON
            var afterAiClosing = ApiResponseAssert.Succeeds(await _harness.AiSubmitsAsync(sessionId, 4)); // 4 closing CON

            Assert.Equal(SessionStatus.InProgress, afterAiClosing.Session.Status);
            Assert.Equal(DebateSide.PRO, afterAiClosing.Session.CurrentTurnSide);
            Assert.Equal(5, afterAiClosing.Session.CurrentTurn!.TurnIndex);

            var final = ApiResponseAssert.Succeeds(await _harness.UserSubmitsAsync(UserA, sessionId)); // 5 closing PRO
            Assert.Equal(SessionStatus.Completed, final.Status);
            Assert.Null(final.CurrentTurn);

            await AssertTranscriptAsync(sessionId,
                (DebateSide.PRO, false), (DebateSide.CON, true), (DebateSide.PRO, false),
                (DebateSide.CON, true), (DebateSide.CON, true), (DebateSide.PRO, false));
        }

        [Fact]
        public async Task AiSession_UserCon_FullFlow_UserSpeaksClosingFirst()
        {
            int sessionId = await _harness.StartAiSessionAsync(DebateSide.CON);

            // Regression: a CON user used to be blocked because an empty round defaulted to PRO.
            ApiResponseAssert.FailsWith(await _harness.UserSubmitsAsync(UserA, sessionId), DebateErrorCodes.NotYourTurn);

            ApiResponseAssert.Succeeds(await _harness.AiSubmitsAsync(sessionId, 0));           // 0 opening PRO
            ApiResponseAssert.Succeeds(await _harness.UserSubmitsAsync(UserA, sessionId));   // 1 opening CON
            ApiResponseAssert.Succeeds(await _harness.AiSubmitsAsync(sessionId, 2));           // 2 rebuttal PRO
            ApiResponseAssert.Succeeds(await _harness.UserSubmitsAsync(UserA, sessionId));   // 3 rebuttal CON
            ApiResponseAssert.Succeeds(await _harness.UserSubmitsAsync(UserA, sessionId));   // 4 closing CON (back-to-back)

            Assert.Equal(SessionStatus.InProgress, _harness.LoadSession(sessionId).Status);

            var final = ApiResponseAssert.Succeeds(await _harness.AiSubmitsAsync(sessionId, 5)); // 5 closing PRO
            Assert.Equal(SessionStatus.Completed, final.Session.Status);

            await AssertTranscriptAsync(sessionId,
                (DebateSide.PRO, true), (DebateSide.CON, false), (DebateSide.PRO, true),
                (DebateSide.CON, false), (DebateSide.CON, false), (DebateSide.PRO, true));
        }

        [Fact]
        public async Task UserSubmit_DuringAiTurn_ReturnsNotYourTurn()
        {
            int sessionId = await _harness.StartAiSessionAsync(DebateSide.PRO);
            ApiResponseAssert.Succeeds(await _harness.UserSubmitsAsync(UserA, sessionId));

            var second = await _harness.UserSubmitsAsync(UserA, sessionId);

            ApiResponseAssert.FailsWith(second, DebateErrorCodes.NotYourTurn);
            Assert.Contains("CON", second.Message);
            Assert.Equal(1, _harness.ArgumentCount(sessionId));
        }

        [Fact]
        public async Task UserSubmit_AfterSixTurns_IsRejected()
        {
            int sessionId = await _harness.StartAiSessionAsync(DebateSide.CON);
            await PlayAiSessionAsUserConAsync(sessionId);

            var extra = await _harness.UserSubmitsAsync(UserA, sessionId);

            Assert.False(extra.Success);
            Assert.Equal(6, _harness.ArgumentCount(sessionId));
        }

        [Fact]
        public async Task UserSubmit_EmptyContent_IsRejected()
        {
            int sessionId = await _harness.StartAiSessionAsync(DebateSide.PRO);

            ApiResponseAssert.FailsWith(await _harness.UserSubmitsAsync(UserA, sessionId, "   "), DebateErrorCodes.InvalidRequest);
            Assert.Equal(0, _harness.ArgumentCount(sessionId));
        }

        [Fact]
        public async Task Rounds_EndOnlyAfterBothTurns_AndNextRoundStarts()
        {
            int sessionId = await _harness.StartAiSessionAsync(DebateSide.PRO);

            ApiResponseAssert.Succeeds(await _harness.UserSubmitsAsync(UserA, sessionId));
            var round1 = _harness.LoadSession(sessionId).DebateRounds.Single(r => r.RoundNumber == 1);
            Assert.Null(round1.EndTime);

            ApiResponseAssert.Succeeds(await _harness.AiSubmitsAsync(sessionId, 1));
            var rounds = _harness.LoadSession(sessionId).DebateRounds;
            Assert.NotNull(rounds.Single(r => r.RoundNumber == 1).EndTime);
            Assert.NotNull(rounds.Single(r => r.RoundNumber == 2).StartTime);
        }

        [Fact]
        public async Task SessionDetails_ReportClosingConAsNextTurn_AfterRebuttal()
        {
            int sessionId = await _harness.StartAiSessionAsync(DebateSide.PRO);
            ApiResponseAssert.Succeeds(await _harness.UserSubmitsAsync(UserA, sessionId));
            ApiResponseAssert.Succeeds(await _harness.AiSubmitsAsync(sessionId, 1));
            ApiResponseAssert.Succeeds(await _harness.UserSubmitsAsync(UserA, sessionId));
            ApiResponseAssert.Succeeds(await _harness.AiSubmitsAsync(sessionId, 3));

            var details = ApiResponseAssert.Succeeds(await _harness.NewService().GetSessionDetailsAsync(UserA, sessionId));

            Assert.Equal(DebateStage.Closing, details.CurrentStage);
            Assert.Equal(DebateSide.CON, details.CurrentTurnSide);
            Assert.Equal(4, details.CurrentTurn!.TurnIndex);
            Assert.Equal(3, details.CurrentTurn.TurnOrder);
        }

        // ---- P2P 1v1: same turn order, behaviour otherwise unchanged ----

        [Fact]
        public async Task P2p_FollowsTurnOrder_ClosingConFirst()
        {
            int sessionId = await _harness.StartP2pSessionAsync(DebateSide.PRO); // A = PRO, B = CON

            ApiResponseAssert.FailsWith(await _harness.UserSubmitsAsync(UserB, sessionId), DebateErrorCodes.NotYourTurn);

            ApiResponseAssert.Succeeds(await _harness.UserSubmitsAsync(UserA, sessionId)); // 0 PRO
            ApiResponseAssert.Succeeds(await _harness.UserSubmitsAsync(UserB, sessionId)); // 1 CON
            ApiResponseAssert.Succeeds(await _harness.UserSubmitsAsync(UserA, sessionId)); // 2 PRO
            ApiResponseAssert.Succeeds(await _harness.UserSubmitsAsync(UserB, sessionId)); // 3 CON

            ApiResponseAssert.FailsWith(await _harness.UserSubmitsAsync(UserA, sessionId), DebateErrorCodes.NotYourTurn);
            ApiResponseAssert.Succeeds(await _harness.UserSubmitsAsync(UserB, sessionId)); // 4 closing CON
            var final = ApiResponseAssert.Succeeds(await _harness.UserSubmitsAsync(UserA, sessionId)); // 5 closing PRO

            Assert.Equal(SessionStatus.Completed, final.Status);
            Assert.Equal(6, _harness.ArgumentCount(sessionId));
        }

        [Fact]
        public async Task P2p_NonParticipant_IsRejected()
        {
            int sessionId = await _harness.StartP2pSessionAsync(DebateSide.PRO);

            ApiResponseAssert.FailsWith(await _harness.UserSubmitsAsync(Outsider, sessionId), DebateErrorCodes.NotParticipant);
        }

        private async Task PlayAiSessionAsUserConAsync(int sessionId)
        {
            ApiResponseAssert.Succeeds(await _harness.AiSubmitsAsync(sessionId, 0));
            ApiResponseAssert.Succeeds(await _harness.UserSubmitsAsync(UserA, sessionId));
            ApiResponseAssert.Succeeds(await _harness.AiSubmitsAsync(sessionId, 2));
            ApiResponseAssert.Succeeds(await _harness.UserSubmitsAsync(UserA, sessionId));
            ApiResponseAssert.Succeeds(await _harness.UserSubmitsAsync(UserA, sessionId));
            ApiResponseAssert.Succeeds(await _harness.AiSubmitsAsync(sessionId, 5));
        }

        private async Task AssertTranscriptAsync(int sessionId, params (DebateSide Side, bool IsAi)[] expected)
        {
            var transcript = ApiResponseAssert.Succeeds(await _harness.NewService().GetTranscriptAsync(UserA, sessionId));
            Assert.Equal(expected, transcript.Arguments.Select(a => (a.Side, a.IsAI)).ToArray());
        }
    }
}
