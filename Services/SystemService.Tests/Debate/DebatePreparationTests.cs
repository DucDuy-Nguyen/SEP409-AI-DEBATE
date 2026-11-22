using SystemService.BLL.Common.Debate;
using SystemService.BLL.DTOs.Debate;
using SystemService.BLL.Services.Debate.Implementations;
using SystemService.DAL.Entities.Debate.Enums;
using SystemService.DAL.Repositories.Debate.Implementations;
using SystemService.DAL.Repositories.Identity.Implementations;
using static SystemService.Tests.Debate.DebateTestHarness;

namespace SystemService.Tests.Debate
{
    /// <summary>
    /// Every debate opens with a preparation minute before Round 1 (only an AI practice may skip it), and the room is
    /// told by a RoundStarted event each time a new round begins.
    /// </summary>
    public class DebatePreparationTests : IDisposable
    {
        private readonly DebateTestHarness _harness = new() { Notifier = new RecordingRealtimeNotifier() };

        public void Dispose() => _harness.Dispose();

        [Fact]
        public async Task Start_OpensWithAPreparationMinute_BeforeRound1()
        {
            int sessionId = await _harness.StartAiSessionAsync(DebateSide.PRO, endPreparation: false);

            var details = ApiResponseAssert.Succeeds(await _harness.NewService().GetSessionDetailsAsync(UserA, sessionId));

            Assert.Equal(SessionStatus.InProgress, details.Status);
            Assert.True(details.IsPreparing);
            Assert.True(details.CanSkipPreparation);
            Assert.Equal(DebatePreparation.Seconds, details.PreparationSeconds);
            Assert.Equal(details.StartedAt!.Value.AddSeconds(DebatePreparation.Seconds), details.PreparationEndsAt);
            Assert.True(details.PreparationEndsAt > details.ServerTime);
            Assert.Equal(3, details.TotalRounds);
            Assert.Equal(1, details.CurrentTurn!.TurnOrder);
            Assert.Equal("Mở đầu", details.CurrentTurn.RoundLabel);
            Assert.Equal(TurnStatus.Pending, details.CurrentTurn.Status);
            Assert.Equal(details.PreparationEndsAt, details.CurrentTurn.StartedAt);

            // Stored: Round 1 starts 60 s after the session
            var stored = _harness.LoadSession(sessionId);
            Assert.Equal(stored.StartTime!.Value.AddSeconds(DebatePreparation.Seconds),
                stored.DebateRounds.Single(r => r.RoundNumber == 1).StartTime);
        }

        [Fact]
        public async Task TwoVsTwo_HasThePreparation_AndRejectsArgumentsDuringIt()
        {
            var created = ApiResponseAssert.Succeeds(await _harness.NewService().Create2v2SessionAsync(UserA, new Create2v2SessionRequest
            {
                Title = "Motion",
                Topic = "Topic",
                UserSide = DebateSide.PRO,
                IsAI = true
            }));
            // Put it in its preparation minute directly (starting a 2v2 needs 4 balanced players, not the point here)
            using (var context = _harness.CreateContext())
            {
                var session = context.DebateSessions.Single(s => s.DebateSessionId == created.SessionId);
                session.Status = SessionStatus.InProgress;
                session.StartTime = DateTime.UtcNow;
                context.DebateRounds.Single(r => r.DebateSessionId == created.SessionId && r.RoundNumber == 1).StartTime =
                    DebatePreparation.FirstRoundStart(session.StartTime.Value);
                context.SaveChanges();
            }

            var details = ApiResponseAssert.Succeeds(await _harness.NewService().GetSessionDetailsAsync(UserA, created.SessionId));
            Assert.True(details.IsPreparing);
            Assert.False(details.CanSkipPreparation);
            ApiResponseAssert.FailsWith(await _harness.UserSubmitsAsync(UserA, created.SessionId), DebateErrorCodes.PreparationInProgress);
            Assert.Equal(0, _harness.ArgumentCount(created.SessionId));
        }

        [Fact]
        public async Task AcceptedChallenge_StartsWithThePreparation()
        {
            using var context = _harness.CreateContext();
            var challenges = new DebateChallengeService(new DebateChallengeRepository(context), new DebateRepository(context), new UserRepository(context));
            var challenge = ApiResponseAssert.Succeeds(await challenges.CreateChallengeAsync(UserA, new CreateChallengeRequest
            {
                ChallengedUserId = UserB,
                Topic = "Students should not have homework",
                ChallengerPreferredSide = DebateSide.PRO
            }));

            var accepted = ApiResponseAssert.Succeeds(await challenges.AcceptChallengeAsync(UserB, challenge.ChallengeId));
            int sessionId = accepted.DebateSessionId!.Value;

            var details = ApiResponseAssert.Succeeds(await _harness.NewService().GetSessionDetailsAsync(UserA, sessionId));
            Assert.True(details.IsPreparing);
            ApiResponseAssert.FailsWith(await _harness.UserSubmitsAsync(UserA, sessionId), DebateErrorCodes.PreparationInProgress);
        }

        [Fact]
        public async Task LeavingDuringPreparation_CancelsTheSession()
        {
            int sessionId = await _harness.StartAiSessionAsync(DebateSide.PRO, endPreparation: false);

            var left = ApiResponseAssert.Succeeds(await _harness.NewService().LeaveSessionAsync(UserA, sessionId));

            Assert.Equal(SessionStatus.Cancelled, left.Status);
            Assert.False(left.IsPreparing);
            ApiResponseAssert.FailsWith(await _harness.NewService().SkipPreparationAsync(UserA, sessionId), DebateErrorCodes.SessionNotInProgress);
        }

        [Fact]
        public async Task DuringPreparation_NoArgumentIsAccepted_FromTheLearnerOrTheAi()
        {
            int proSession = await _harness.StartAiSessionAsync(DebateSide.PRO, endPreparation: false);
            int conSession = await _harness.StartAiSessionAsync(DebateSide.CON, endPreparation: false);

            ApiResponseAssert.FailsWith(await _harness.UserSubmitsAsync(UserA, proSession), DebateErrorCodes.PreparationInProgress);
            ApiResponseAssert.FailsWith(await _harness.AiSubmitsAsync(conSession, 0), DebateErrorCodes.PreparationInProgress);

            Assert.Equal(0, _harness.ArgumentCount(proSession));
            Assert.Equal(0, _harness.ArgumentCount(conSession));
        }

        [Fact]
        public async Task P2pRoom_HasThePreparation_AndCannotSkipIt()
        {
            int sessionId = await _harness.StartP2pSessionAsync(DebateSide.PRO, endPreparation: false);

            var details = ApiResponseAssert.Succeeds(await _harness.NewService().GetSessionDetailsAsync(UserA, sessionId));
            Assert.True(details.IsPreparing);
            Assert.False(details.CanSkipPreparation);

            ApiResponseAssert.FailsWith(await _harness.NewService().SkipPreparationAsync(UserA, sessionId), DebateErrorCodes.NotAiSession);
            ApiResponseAssert.FailsWith(await _harness.UserSubmitsAsync(UserA, sessionId), DebateErrorCodes.PreparationInProgress);
            Assert.True(ApiResponseAssert.Succeeds(await _harness.NewService().GetSessionDetailsAsync(UserB, sessionId)).IsPreparing);
        }

        [Fact]
        public async Task AiPractice_SkipPreparation_StartsRound1Now_AndAnnouncesIt()
        {
            int sessionId = await _harness.StartAiSessionAsync(DebateSide.PRO, endPreparation: false);

            var skipped = ApiResponseAssert.Succeeds(await _harness.NewService().SkipPreparationAsync(UserA, sessionId));

            Assert.False(skipped.IsPreparing);
            Assert.False(skipped.CanSkipPreparation);
            Assert.Equal(TurnStatus.Active, skipped.CurrentTurn!.Status);
            Assert.True(skipped.PreparationEndsAt <= skipped.ServerTime);
            Assert.Equal(new[] { 1 }, _harness.Notifier!.RoundsStarted());
            ApiResponseAssert.Succeeds(await _harness.UserSubmitsAsync(UserA, sessionId));

            // Skipping again changes nothing and announces nothing
            ApiResponseAssert.Succeeds(await _harness.NewService().SkipPreparationAsync(UserA, sessionId));
            Assert.Equal(new[] { 1 }, _harness.Notifier.RoundsStarted());
        }

        [Fact]
        public async Task SkipPreparation_OnlyByAParticipant()
        {
            int sessionId = await _harness.StartAiSessionAsync(DebateSide.PRO, endPreparation: false);

            ApiResponseAssert.FailsWith(await _harness.NewService().SkipPreparationAsync(Outsider, sessionId), DebateErrorCodes.NotParticipant);
            Assert.True(ApiResponseAssert.Succeeds(await _harness.NewService().GetSessionDetailsAsync(UserA, sessionId)).IsPreparing);
        }

        [Fact]
        public async Task P2pDebate_AnnouncesRound2And3_NotTheEnd()
        {
            int sessionId = await _harness.StartP2pSessionAsync(DebateSide.PRO); // A = PRO, B = CON

            // Turn order: R1 PRO, CON - R2 PRO, CON - R3 CON, PRO
            foreach (int user in new[] { UserA, UserB, UserA, UserB, UserB, UserA })
            {
                ApiResponseAssert.Succeeds(await _harness.UserSubmitsAsync(user, sessionId));
            }

            Assert.Equal(new[] { 2, 3 }, _harness.Notifier!.RoundsStarted());
            var round2 = _harness.Notifier.Events.First(e => e.Event == "RoundStarted").Data!;
            Assert.Equal("Phản biện", round2.GetType().GetProperty("RoundLabel")!.GetValue(round2));
        }

        [Fact]
        public async Task AiPractice_TheAiTurnEndingARound_AnnouncesTheNextOne()
        {
            int sessionId = await _harness.StartAiSessionAsync(DebateSide.PRO);

            ApiResponseAssert.Succeeds(await _harness.UserSubmitsAsync(UserA, sessionId)); // turn 0, PRO
            Assert.Empty(_harness.Notifier!.RoundsStarted());

            ApiResponseAssert.Succeeds(await _harness.AiSubmitsAsync(sessionId, 1)); // turn 1, CON: Round 1 over
            Assert.Equal(new[] { 2 }, _harness.Notifier.RoundsStarted());
        }
    }
}
