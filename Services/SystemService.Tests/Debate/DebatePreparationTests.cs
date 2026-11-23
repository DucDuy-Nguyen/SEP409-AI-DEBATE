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
    /// Every round opens with a preparation minute, Round 1 and between rounds (only an AI practice may skip it), and
    /// the room is told by a RoundStarted event each time the debate moves to a new round.
    /// </summary>
    public class DebatePreparationTests : IDisposable
    {
        private readonly DebateTestHarness _harness = new() { Notifier = new RecordingRealtimeNotifier(), AutoEndPreparation = false };

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
                Category = "education",
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
                    DebatePreparation.RoundStart(session.StartTime.Value);
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
                Category = "education",
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
        public async Task PreparationTimes_GoOutAsUtc_EvenWhenTheDatabaseGivesThemBackWithoutAKind()
        {
            int sessionId = await _harness.StartAiSessionAsync(DebateSide.PRO, endPreparation: false);
            // SQL Server reads datetime2 back with Kind Unspecified (InMemory keeps the Kind): store it that way
            var endsAt = DateTime.SpecifyKind(DateTime.UtcNow.AddSeconds(30), DateTimeKind.Unspecified);
            using (var context = _harness.CreateContext())
            {
                context.DebateRounds.Single(r => r.DebateSessionId == sessionId && r.RoundNumber == 1).StartTime = endsAt;
                context.SaveChanges();
            }

            var details = ApiResponseAssert.Succeeds(await _harness.NewService().GetSessionDetailsAsync(UserA, sessionId));

            Assert.True(details.IsPreparing);
            Assert.Equal(DateTimeKind.Utc, details.PreparationEndsAt!.Value.Kind);
            Assert.Equal(DateTimeKind.Utc, details.CurrentTurn!.StartedAt!.Value.Kind);
            Assert.Equal(DateTimeKind.Utc, details.StartedAt!.Value.Kind);
            Assert.Equal(endsAt.Ticks, details.PreparationEndsAt.Value.Ticks);
            // JSON (what the browser parses) carries the zone
            Assert.EndsWith("Z\"", System.Text.Json.JsonSerializer.Serialize(details.PreparationEndsAt));
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
                _harness.EndPreparation(sessionId);
                ApiResponseAssert.Succeeds(await _harness.UserSubmitsAsync(user, sessionId));
            }

            Assert.Equal(new[] { 2, 3 }, _harness.Notifier!.RoundsStarted());
            var round2 = _harness.Notifier.Events.First(e => e.Event == "RoundStarted").Data!;
            Assert.Equal("Phản biện", round2.GetType().GetProperty("RoundLabel")!.GetValue(round2));

            var done = ApiResponseAssert.Succeeds(await _harness.NewService().GetSessionDetailsAsync(UserA, sessionId));
            Assert.Equal(SessionStatus.Completed, done.Status);
            Assert.False(done.IsPreparing);
            Assert.Null(done.PreparationEndsAt);
        }

        [Fact]
        public async Task BetweenRounds_TheNextRoundOpensWithAPreparationMinute()
        {
            int sessionId = await _harness.StartP2pSessionAsync(DebateSide.PRO); // A = PRO, B = CON
            ApiResponseAssert.Succeeds(await _harness.UserSubmitsAsync(UserA, sessionId));

            var endOfRound1 = ApiResponseAssert.Succeeds(await _harness.UserSubmitsAsync(UserB, sessionId));

            Assert.Equal(2, endOfRound1.CurrentTurn!.TurnOrder);
            Assert.True(endOfRound1.IsPreparing);
            Assert.Equal(TurnStatus.Pending, endOfRound1.CurrentTurn.Status);
            Assert.Equal(endOfRound1.PreparationEndsAt, endOfRound1.CurrentTurn.StartedAt);
            var secondsLeft = (endOfRound1.PreparationEndsAt!.Value - endOfRound1.ServerTime).TotalSeconds;
            Assert.InRange(secondsLeft, DebatePreparation.Seconds - 5, DebatePreparation.Seconds);
            ApiResponseAssert.FailsWith(await _harness.UserSubmitsAsync(UserA, sessionId), DebateErrorCodes.PreparationInProgress);

            var round2 = _harness.Notifier!.Events.Single(e => e.Event == "RoundStarted").Data!;
            Assert.Equal(true, round2.GetType().GetProperty("IsPreparing")!.GetValue(round2));

            _harness.EndPreparation(sessionId);
            ApiResponseAssert.Succeeds(await _harness.UserSubmitsAsync(UserA, sessionId));
        }

        [Fact]
        public async Task AiPractice_SkipsThePreparationBetweenRounds_Too()
        {
            int sessionId = await _harness.StartAiSessionAsync(DebateSide.PRO);
            ApiResponseAssert.Succeeds(await _harness.UserSubmitsAsync(UserA, sessionId)); // turn 0
            ApiResponseAssert.Succeeds(await _harness.AiSubmitsAsync(sessionId, 1)); // turn 1: Round 2 prepares

            var skipped = ApiResponseAssert.Succeeds(await _harness.NewService().SkipPreparationAsync(UserA, sessionId));

            Assert.False(skipped.IsPreparing);
            Assert.Equal(2, skipped.CurrentTurn!.TurnOrder);
            ApiResponseAssert.Succeeds(await _harness.UserSubmitsAsync(UserA, sessionId)); // turn 2, Round 2
        }

        [Fact]
        public async Task AiPractice_RestartPreparation_CountsTheMinuteFromNow_AndAnnouncesIt()
        {
            int sessionId = await _harness.StartAiSessionAsync(DebateSide.PRO);
            ApiResponseAssert.Succeeds(await _harness.UserSubmitsAsync(UserA, sessionId)); // turn 0
            ApiResponseAssert.Succeeds(await _harness.AiSubmitsAsync(sessionId, 1)); // turn 1: Round 2 prepares
            _harness.ShiftLastTurnBack(sessionId, 50); // the AI read aloud for 50 s: 10 s of the minute left

            var restarted = ApiResponseAssert.Succeeds(await _harness.NewService().RestartPreparationAsync(UserA, sessionId));

            Assert.True(restarted.IsPreparing);
            Assert.Equal(2, restarted.CurrentTurn!.TurnOrder);
            Assert.Equal(restarted.PreparationEndsAt, restarted.CurrentTurn.StartedAt);
            var secondsLeft = (restarted.PreparationEndsAt!.Value - restarted.ServerTime).TotalSeconds;
            Assert.InRange(secondsLeft, DebatePreparation.Seconds - 5, DebatePreparation.Seconds);
            Assert.Equal(new[] { 2, 2 }, _harness.Notifier!.RoundsStarted()); // the AI turn, then the restart
            ApiResponseAssert.FailsWith(await _harness.UserSubmitsAsync(UserA, sessionId), DebateErrorCodes.PreparationInProgress);

            _harness.EndPreparation(sessionId);
            ApiResponseAssert.Succeeds(await _harness.UserSubmitsAsync(UserA, sessionId)); // turn 2, Round 2
        }

        [Fact]
        public async Task AiPractice_RestartPreparation_AfterTheMinuteRanOutDuringTheReading_PreparesAgain()
        {
            int sessionId = await _harness.StartAiSessionAsync(DebateSide.PRO);
            ApiResponseAssert.Succeeds(await _harness.UserSubmitsAsync(UserA, sessionId)); // turn 0
            ApiResponseAssert.Succeeds(await _harness.AiSubmitsAsync(sessionId, 1)); // turn 1: Round 2 prepares
            _harness.ShiftLastTurnBack(sessionId, 90); // the AI read aloud for longer than the minute

            var restarted = ApiResponseAssert.Succeeds(await _harness.NewService().RestartPreparationAsync(UserA, sessionId));

            Assert.True(restarted.IsPreparing);
            var secondsLeft = (restarted.PreparationEndsAt!.Value - restarted.ServerTime).TotalSeconds;
            Assert.InRange(secondsLeft, DebatePreparation.Seconds - 5, DebatePreparation.Seconds);
            ApiResponseAssert.FailsWith(await _harness.UserSubmitsAsync(UserA, sessionId), DebateErrorCodes.PreparationInProgress);
        }

        [Fact]
        public async Task RestartPreparation_OncePerAiTurn_ItCannotReArmTheMinute()
        {
            int sessionId = await _harness.StartAiSessionAsync(DebateSide.PRO);
            ApiResponseAssert.Succeeds(await _harness.UserSubmitsAsync(UserA, sessionId)); // turn 0
            ApiResponseAssert.Succeeds(await _harness.AiSubmitsAsync(sessionId, 1)); // turn 1: Round 2 prepares
            _harness.ShiftLastTurnBack(sessionId, 90); // the AI read for 90 s: the minute ran out 30 s ago

            Assert.True(ApiResponseAssert.Succeeds(await _harness.NewService().RestartPreparationAsync(UserA, sessionId)).IsPreparing);

            _harness.EndPreparation(sessionId); // the restarted minute has passed too
            var again = ApiResponseAssert.Succeeds(await _harness.NewService().RestartPreparationAsync(UserA, sessionId));
            Assert.False(again.IsPreparing);
            Assert.Equal(new[] { 2, 2 }, _harness.Notifier!.RoundsStarted()); // the AI turn, then one restart
            ApiResponseAssert.Succeeds(await _harness.UserSubmitsAsync(UserA, sessionId)); // turn 2, Round 2
        }

        [Fact]
        public async Task RestartPreparation_NeverShortensIt()
        {
            int sessionId = await _harness.StartAiSessionAsync(DebateSide.PRO);
            ApiResponseAssert.Succeeds(await _harness.UserSubmitsAsync(UserA, sessionId));
            ApiResponseAssert.Succeeds(await _harness.AiSubmitsAsync(sessionId, 1));
            _harness.SetPreparationEndsIn(sessionId, DebatePreparation.Seconds + 30); // ends later than now + 60 s
            var before = ApiResponseAssert.Succeeds(await _harness.NewService().GetSessionDetailsAsync(UserA, sessionId));

            var same = ApiResponseAssert.Succeeds(await _harness.NewService().RestartPreparationAsync(UserA, sessionId));

            Assert.Equal(before.PreparationEndsAt, same.PreparationEndsAt);
            Assert.Equal(new[] { 2 }, _harness.Notifier!.RoundsStarted()); // only the AI turn announced Round 2
        }

        [Fact]
        public async Task RestartPreparation_OnlyRightAfterTheAiTurnEndedARound()
        {
            // Round 1: nobody has spoken yet, so there is no AI reading to wait for
            int round1 = await _harness.StartAiSessionAsync(DebateSide.PRO, endPreparation: false);
            _harness.EndPreparation(round1);
            var notMoved = ApiResponseAssert.Succeeds(await _harness.NewService().RestartPreparationAsync(UserA, round1));
            Assert.False(notMoved.IsPreparing);

            // Round 2 after the learner has spoken in it: the round is never sent back to preparing
            int sessionId = await _harness.StartAiSessionAsync(DebateSide.PRO);
            ApiResponseAssert.Succeeds(await _harness.UserSubmitsAsync(UserA, sessionId)); // turn 0
            ApiResponseAssert.Succeeds(await _harness.AiSubmitsAsync(sessionId, 1)); // turn 1
            _harness.EndPreparation(sessionId);
            ApiResponseAssert.Succeeds(await _harness.UserSubmitsAsync(UserA, sessionId)); // turn 2, Round 2
            var underWay = ApiResponseAssert.Succeeds(await _harness.NewService().RestartPreparationAsync(UserA, sessionId));
            Assert.False(underWay.IsPreparing);
            Assert.Empty(_harness.Notifier!.RoundsStarted().Where(r => r == 1)); // nothing announced for Round 1
        }

        [Fact]
        public async Task AiPractice_LearnerPro_TheAiClosesRebuttalThenOpensClosing_DuringThePreparation()
        {
            int sessionId = await _harness.StartAiSessionAsync(DebateSide.PRO);
            ApiResponseAssert.Succeeds(await _harness.UserSubmitsAsync(UserA, sessionId)); // turn 0
            ApiResponseAssert.Succeeds(await _harness.AiSubmitsAsync(sessionId, 1));      // turn 1: Round 2 prepares
            _harness.EndPreparation(sessionId);
            ApiResponseAssert.Succeeds(await _harness.UserSubmitsAsync(UserA, sessionId)); // turn 2
            ApiResponseAssert.Succeeds(await _harness.AiSubmitsAsync(sessionId, 3));      // turn 3: Round 3 prepares

            // The AI's closing right away, inside the minute: accepted, and the minute stays the learner's
            var closing = ApiResponseAssert.Succeeds(await _harness.AiSubmitsAsync(sessionId, 4));
            Assert.True(closing.Session!.IsPreparing);
            Assert.Equal(5, closing.Session.CurrentTurn!.TurnIndex);
            ApiResponseAssert.FailsWith(await _harness.UserSubmitsAsync(UserA, sessionId), DebateErrorCodes.PreparationInProgress);

            // Both speeches read aloud for 90 s: the minute counts from the end of the reading, once
            _harness.ShiftLastTurnBack(sessionId, 90);
            var before = DateTime.UtcNow;
            var restarted = ApiResponseAssert.Succeeds(await _harness.NewService().RestartPreparationAsync(UserA, sessionId));
            Assert.True(restarted.IsPreparing);
            Assert.True(restarted.PreparationEndsAt >= before.AddSeconds(DebatePreparation.Seconds));
            var again = ApiResponseAssert.Succeeds(await _harness.NewService().RestartPreparationAsync(UserA, sessionId));
            Assert.Equal(restarted.PreparationEndsAt, again.PreparationEndsAt);
        }

        [Fact]
        public async Task AiPractice_LearnerCon_TheAiOpensRebuttal_DuringThePreparation_ThenTheMinuteRestarts()
        {
            int sessionId = await _harness.StartAiSessionAsync(DebateSide.CON);
            ApiResponseAssert.Succeeds(await _harness.AiSubmitsAsync(sessionId, 0));      // turn 0
            ApiResponseAssert.Succeeds(await _harness.UserSubmitsAsync(UserA, sessionId)); // turn 1: Round 2 prepares

            var rebuttal = ApiResponseAssert.Succeeds(await _harness.AiSubmitsAsync(sessionId, 2));
            Assert.True(rebuttal.Session!.IsPreparing);

            _harness.ShiftLastTurnBack(sessionId, 90);
            var restarted = ApiResponseAssert.Succeeds(await _harness.NewService().RestartPreparationAsync(UserA, sessionId));
            Assert.True(restarted.IsPreparing);
            Assert.Equal(3, restarted.CurrentTurn!.TurnIndex);
        }

        [Fact]
        public async Task RestartPreparation_TwiceRightAfterTheAiTurn_DoesNotReArmIt()
        {
            int sessionId = await _harness.StartAiSessionAsync(DebateSide.PRO);
            ApiResponseAssert.Succeeds(await _harness.UserSubmitsAsync(UserA, sessionId)); // turn 0
            ApiResponseAssert.Succeeds(await _harness.AiSubmitsAsync(sessionId, 1));      // turn 1: Round 2 prepares

            // No reading aloud: the browser restarts at once, then again
            var first = ApiResponseAssert.Succeeds(await _harness.NewService().RestartPreparationAsync(UserA, sessionId));
            await Task.Delay(50);
            var second = ApiResponseAssert.Succeeds(await _harness.NewService().RestartPreparationAsync(UserA, sessionId));
            Assert.True(first.IsPreparing);
            Assert.Equal(first.PreparationEndsAt, second.PreparationEndsAt);
        }

        [Fact]
        public async Task RestartPreparation_NotAfterTheAiOpening_OfRound1()
        {
            int sessionId = await _harness.StartAiSessionAsync(DebateSide.CON);
            ApiResponseAssert.Succeeds(await _harness.AiSubmitsAsync(sessionId, 0));
            var notMoved = ApiResponseAssert.Succeeds(await _harness.NewService().RestartPreparationAsync(UserA, sessionId));
            Assert.False(notMoved.IsPreparing);
        }

        [Fact]
        public async Task RestartPreparation_OnlyForAParticipantOfAnAiPractice()
        {
            int aiSession = await _harness.StartAiSessionAsync(DebateSide.PRO, endPreparation: false);
            ApiResponseAssert.FailsWith(await _harness.NewService().RestartPreparationAsync(Outsider, aiSession), DebateErrorCodes.NotParticipant);

            int p2pSession = await _harness.StartP2pSessionAsync(DebateSide.PRO);
            ApiResponseAssert.FailsWith(await _harness.NewService().RestartPreparationAsync(UserA, p2pSession), DebateErrorCodes.NotAiSession);
        }

        [Fact]
        public async Task AiPractice_TheAiTurnEndingARound_AnnouncesTheNextOne()
        {
            int sessionId = await _harness.StartAiSessionAsync(DebateSide.PRO);

            ApiResponseAssert.Succeeds(await _harness.UserSubmitsAsync(UserA, sessionId)); // turn 0, PRO
            Assert.Empty(_harness.Notifier!.RoundsStarted());

            ApiResponseAssert.Succeeds(await _harness.AiSubmitsAsync(sessionId, 1)); // turn 1, CON: Round 1 over
            Assert.Equal(new[] { 2 }, _harness.Notifier.RoundsStarted());
            var payload = _harness.Notifier.Events.Single(e => e.Event == "RoundStarted").Data!;
            Assert.Equal(true, payload.GetType().GetProperty("IsPreparing")!.GetValue(payload));
        }
    }
}
