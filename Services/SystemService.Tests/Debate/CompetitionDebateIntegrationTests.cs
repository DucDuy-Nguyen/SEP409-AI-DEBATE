using SystemService.DAL.Entities.Competition;
using SystemService.DAL.Entities.Debate.Enums;
using static SystemService.Tests.Debate.DebateTestHarness;
using FakeEvaluatorClient = SystemService.Tests.Debate.DebateAiEvaluatorIntegrationTests.FakeEvaluatorClient;

namespace SystemService.Tests.Debate
{
    /// <summary>
    /// WF-03: the last turn of a competition debate completes the session, moves the linked match to "Evaluating" and
    /// auto-evaluates it; a GET /evaluation arriving meanwhile shares that evaluation (one AIJudgement).
    /// </summary>
    public class CompetitionDebateIntegrationTests : IDisposable
    {
        private readonly DebateTestHarness _harness = new();

        public void Dispose() => _harness.Dispose();

        [Fact]
        public async Task LastTurn_MovesMatchToEvaluating_AndAutoEvaluatesOnce_EvenWithAConcurrentGet()
        {
            int sessionId = await _harness.StartP2pSessionAsync(DebateSide.PRO); // UserA PRO, UserB CON
            int matchId = SeedOngoingMatch(sessionId);

            // Backend turn order: PRO, CON, PRO, CON, CON, PRO
            foreach (var user in new[] { UserA, UserB, UserA, UserB, UserB })
            {
                ApiResponseAssert.Succeeds(await _harness.UserSubmitsAsync(user, sessionId));
            }
            Assert.Equal("Ongoing", MatchStatus(matchId));

            var client = new FakeEvaluatorClient(_ => 300);
            _harness.AiEvaluator = client;

            var lastTurn = _harness.UserSubmitsAsync(UserA, sessionId);
            // The other debater opens the result while the auto-evaluation is still running
            await WaitUntilAsync(() => _harness.Coordinator.IsRunning(sessionId));
            var concurrentGet = _harness.NewService().GetSessionEvaluationAsync(UserB, sessionId);

            var submitted = ApiResponseAssert.Succeeds(await lastTurn);
            var seenByB = ApiResponseAssert.Succeeds(await concurrentGet);
            var seenByA = ApiResponseAssert.Succeeds(await _harness.NewService().GetSessionEvaluationAsync(UserA, sessionId));

            Assert.Equal(SessionStatus.Completed, submitted.Status);
            Assert.Equal("Evaluating", MatchStatus(matchId));
            Assert.Equal(6, client.RoundRequests.Count);
            Assert.Equal(2, client.SessionRequests.Count);
            Assert.Equal(1, JudgementCount(sessionId));
            Assert.Equal(seenByA.JudgementId, seenByB.JudgementId);
            Assert.Equal(seenByA.OverallScorePro, seenByB.OverallScorePro);
            Assert.Equal(seenByA.OverallScoreCon, seenByB.OverallScoreCon);
        }

        [Fact]
        public async Task FailedAutoEvaluation_StillCompletesTheSession_AndTheMatchWaitsInEvaluating()
        {
            int sessionId = await _harness.StartP2pSessionAsync(DebateSide.PRO);
            int matchId = SeedOngoingMatch(sessionId);
            foreach (var user in new[] { UserA, UserB, UserA, UserB, UserB })
            {
                ApiResponseAssert.Succeeds(await _harness.UserSubmitsAsync(user, sessionId));
            }
            _harness.AiEvaluator = new FakeEvaluatorClient { FailStage = "opening" };

            var submitted = ApiResponseAssert.Succeeds(await _harness.UserSubmitsAsync(UserA, sessionId));

            Assert.Equal(SessionStatus.Completed, submitted.Status);
            Assert.Equal("Evaluating", MatchStatus(matchId));
            Assert.Equal(0, JudgementCount(sessionId));

            // Evaluation on demand afterwards works and creates the judgement the official review needs
            _harness.AiEvaluator = new FakeEvaluatorClient();
            ApiResponseAssert.Succeeds(await _harness.NewService().GetSessionEvaluationAsync(UserB, sessionId));
            Assert.Equal(1, JudgementCount(sessionId));
            Assert.Equal("Evaluating", MatchStatus(matchId));
        }

        private int SeedOngoingMatch(int sessionId)
        {
            using var context = _harness.CreateContext();
            var competition = new Competition
            {
                Title = "Giải thử",
                CreatedBy = Outsider,
                CompetitionType = "Individual",
                Status = "Ongoing",
                RegistrationStart = DateTime.UtcNow.AddDays(-3),
                RegistrationEnd = DateTime.UtcNow.AddDays(-2),
                StartDate = DateTime.UtcNow.AddDays(-1),
            };
            var round = new CompetitionRound { Competition = competition, RoundNumber = 1, RoundName = "Vòng 1", Status = "Ongoing" };
            var match = new CompetitionMatch
            {
                Competition = competition,
                Round = round,
                DebateSessionId = sessionId,
                MatchNumber = 1,
                Status = "Ongoing",
                AssignedJudgeUserId = Outsider,
                RowVersion = new byte[8],
            };
            context.CompetitionMatches.Add(match);
            context.SaveChanges();
            return match.CompetitionMatchId;
        }

        private string MatchStatus(int matchId)
        {
            using var context = _harness.CreateContext();
            return context.CompetitionMatches.Single(m => m.CompetitionMatchId == matchId).Status;
        }

        private int JudgementCount(int sessionId)
        {
            using var context = _harness.CreateContext();
            return context.AIJudgements.Count(j => j.DebateSessionId == sessionId);
        }

        private static async Task WaitUntilAsync(Func<bool> condition)
        {
            for (int i = 0; i < 200 && !condition(); i++)
            {
                await Task.Delay(10);
            }
            Assert.True(condition(), "Timed out waiting for the auto-evaluation to start");
        }
    }
}
