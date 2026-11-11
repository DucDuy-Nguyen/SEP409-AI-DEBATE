using System.Collections.Concurrent;
using System.Text.Json;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using SystemService.BLL.DTOs.AI;
using SystemService.BLL.DTOs.Debate;
using SystemService.BLL.Services.AI.Interfaces;
using SystemService.BLL.Services.Debate.Implementations;
using SystemService.BLL.Services.Debate.Interfaces;
using SystemService.DAL.Repositories.Debate.Implementations;
using SystemService.DAL.Repositories.Identity.Implementations;
using SystemService.DAL.Entities.Debate;
using SystemService.DAL.Entities.Debate.Enums;
using static SystemService.Tests.Debate.DebateTestHarness;

namespace SystemService.Tests.Debate
{
    /// <summary>
    /// Cham phien qua AI Evaluator (fake client, khong goi HTTP): topic, check_evidence, goi song song,
    /// evidence_checks trong GET /evaluation, judgement cu khong co evidence.
    /// </summary>
    public class DebateAiEvaluatorIntegrationTests : IDisposable
    {
        private readonly DebateTestHarness _harness = new();

        public void Dispose() => _harness.Dispose();

        [Theory]
        [InlineData("Education", "education")]
        [InlineData("  TECHNOLOGY ", "technology")]
        [InlineData("society", "society")]
        [InlineData("Chính trị", null)]
        [InlineData(null, null)]
        public async Task RoundRequest_CarriesTopicMappedFromCategory(string? category, string? expectedTopic)
        {
            int sessionId = await SeedAiSessionAsync(category);
            var client = new FakeEvaluatorClient();

            ApiResponseAssert.Succeeds(await _harness.NewService(client).EvaluateSessionAsync(UserA, sessionId));

            Assert.Equal(6, client.RoundRequests.Count);
            Assert.All(client.RoundRequests, r => Assert.Equal(expectedTopic, r.Topic));
        }

        [Fact]
        public async Task AiPractice_AiSideRequest_HasCheckEvidenceFalse()
        {
            int sessionId = await SeedAiSessionAsync("Education", userSide: DebateSide.PRO);
            var client = new FakeEvaluatorClient();

            ApiResponseAssert.Succeeds(await _harness.NewService(client).EvaluateSessionAsync(UserA, sessionId));

            Assert.All(client.RoundRequests.Where(r => r.Side == "pro"), r => Assert.True(r.CheckEvidence));
            Assert.All(client.RoundRequests.Where(r => r.Side == "con"), r => Assert.False(r.CheckEvidence));
            Assert.Equal(3, client.RoundRequests.Count(r => r.Side == "con"));

            // JSON gui Python dung snake_case
            var json = JsonSerializer.Serialize(client.RoundRequests.First(r => r.Side == "con"));
            Assert.Contains("\"check_evidence\":false", json);
            Assert.Contains("\"topic\":\"education\"", json);
        }

        [Fact]
        public async Task P2pSession_BothSidesCheckEvidence()
        {
            int sessionId = await SeedP2pSessionAsync("Environment");
            var client = new FakeEvaluatorClient();

            ApiResponseAssert.Succeeds(await _harness.NewService(client).EvaluateSessionAsync(UserA, sessionId));

            Assert.Equal(6, client.RoundRequests.Count);
            Assert.All(client.RoundRequests, r => Assert.True(r.CheckEvidence));
        }

        [Fact]
        public async Task RoundCalls_RunInParallel_AndKeepRoundOrder()
        {
            int sessionId = await SeedAiSessionAsync("Education");
            // Opening tra ve cham nhat: neu gom theo thu tu xong thi thu tu round se dao
            var client = new FakeEvaluatorClient(stage => stage switch
            {
                "opening" => 300,
                "rebuttal" => 150,
                _ => 0
            });

            var result = ApiResponseAssert.Succeeds(await _harness.NewService(client).EvaluateSessionAsync(UserA, sessionId));

            Assert.Equal(6, client.MaxConcurrentRounds);
            Assert.Equal(2, client.MaxConcurrentSessions);
            Assert.Equal(new[] { "opening", "rebuttal", "closing" }, result.ProEvaluation!.RoundEvaluations.Select(r => r.Stage));
            Assert.Equal(new[] { "opening", "rebuttal", "closing" }, result.ConEvaluation!.RoundEvaluations.Select(r => r.Stage));
            Assert.Equal(new[] { 1, 2, 3 }, result.ProEvaluation.RoundEvaluations.Select(r => r.RoundNumber));

            // Session nhan round dung thu tu
            Assert.Equal(new[] { "opening", "rebuttal", "closing" },
                client.SessionRequests.Single(s => s.Side == "pro").Rounds.Select(r => r.Stage));
        }

        [Fact]
        public async Task EvidenceChecks_ReturnedPerRoundAndSide_WithoutError()
        {
            int sessionId = await SeedAiSessionAsync("Education");
            var client = new FakeEvaluatorClient { WithEvidence = true };
            ApiResponseAssert.Succeeds(await _harness.NewService(client).EvaluateSessionAsync(UserA, sessionId));

            var result = ApiResponseAssert.Succeeds(await _harness.NewService().GetSessionEvaluationAsync(UserA, sessionId));

            foreach (var (eval, side) in new[] { (result.ProEvaluation!, "pro"), (result.ConEvaluation!, "con") })
            {
                foreach (var round in eval.RoundEvaluations)
                {
                    var check = Assert.Single(round.EvidenceChecks!);
                    Assert.Equal($"{side}-{round.Stage}", check.Excerpt);
                    Assert.Equal("unavailable", check.EvidenceCheck.Status);
                    var claim = Assert.Single(check.EvidenceCheck.Claims);
                    Assert.Equal("CONTRADICTED", claim.Label);
                    Assert.Equal("fact-1", Assert.Single(claim.Citations).FactId);
                    Assert.Equal(4, round.EvidenceScoreBefore);
                    Assert.Equal(3, round.EvidenceScoreAfter);
                    Assert.Equal($"rule-{side}-{round.Stage}", round.EvidenceRuleApplied);
                }
            }

            // FE khong nhan field error; ban luu trong RawResponseJson van giu
            var feJson = JsonSerializer.Serialize(result, new JsonSerializerOptions(JsonSerializerDefaults.Web));
            Assert.Contains("\"evidenceChecks\"", feJson);
            Assert.Contains("\"factId\":\"fact-1\"", feJson);
            Assert.DoesNotContain("TimeoutError", feJson);
            Assert.DoesNotContain("\"error\"", feJson);
            Assert.Contains("TimeoutError: verify qua 20 s", StoredRawJson(sessionId));
        }

        [Fact]
        public async Task RoundWithoutEvidence_StillStoresJudgement()
        {
            int sessionId = await SeedAiSessionAsync("Education");
            var client = new FakeEvaluatorClient { WithEvidence = false };

            var result = ApiResponseAssert.Succeeds(await _harness.NewService(client).EvaluateSessionAsync(UserA, sessionId));

            Assert.All(result.ProEvaluation!.RoundEvaluations, r => Assert.Null(r.EvidenceChecks));
            Assert.Equal(7.0m, result.OverallScorePro);
        }

        [Fact]
        public async Task RoundException_FailsEvaluation_AndStoresNoJudgement()
        {
            int sessionId = await SeedAiSessionAsync("Education");
            var client = new FakeEvaluatorClient { FailStage = "rebuttal" };

            var result = await _harness.NewService(client).EvaluateSessionAsync(UserA, sessionId);

            Assert.False(result.Success);
            Assert.Empty(client.SessionRequests);
            using var context = _harness.CreateContext();
            Assert.False(context.AIJudgements.Any(j => j.DebateSessionId == sessionId));
        }

        [Fact]
        public async Task NullRoundResponse_IsSkipped()
        {
            int sessionId = await SeedAiSessionAsync("Education");
            var client = new FakeEvaluatorClient { NullStage = "rebuttal" };

            var result = ApiResponseAssert.Succeeds(await _harness.NewService(client).EvaluateSessionAsync(UserA, sessionId));

            Assert.Equal(new[] { "opening", "closing" }, result.ProEvaluation!.RoundEvaluations.Select(r => r.Stage));
            Assert.Equal(new[] { "opening", "closing" },
                client.SessionRequests.Single(s => s.Side == "pro").Rounds.Select(r => r.Stage));
        }

        [Fact]
        public void RoundRequest_WireFormat()
        {
            var json = JsonSerializer.Serialize(new EvaluateRoundRequest("m", "pro", "opening", new() { new RoundTurnDto("learner", "t") }));
            Assert.Contains("\"topic\":null", json); // Python: Optional -> null hop le
            Assert.Contains("\"check_evidence\":true", json);
        }

        [Fact]
        public void SessionRequest_OmitsNullEvidenceFields()
        {
            // Python: cac field str/list khong nhan null -> phai bo qua khi null
            var round = new EvaluateRoundResponse("opening", 7.0m, new(), "note", new(), new(), new(),
                EvidenceChecks: new() { new TurnEvidenceCheckDto(0, "x", new EvidenceCheckSummaryDto("no_claims")) });
            var json = JsonSerializer.Serialize(new EvaluateSessionRequest("m", "pro", new() { round }));

            Assert.DoesNotContain("null", json);
            Assert.Contains("\"evidence_checks\":[{\"turn_index\":0,\"excerpt\":\"x\",\"evidence_check\":{\"status\":\"no_claims\"}}]", json);
        }

        [Fact]
        public void PythonRoundResponse_DeserializesAllEvidenceFields()
        {
            const string json = """
            {"stage":"opening","round_score":7.5,"criteria":[],"consistency_note":"n","strengths":[],"weaknesses":[],"suggestions":[],
             "raw_model_output":null,"scoring_version":"v2_4x25",
             "evidence_checks":[{"turn_index":0,"excerpt":"e","evidence_check":{"status":"no_fact_base","claims":[],"counts":{},
               "evidence_score_before":null,"evidence_score_after":null,"rule_applied":"","error":null,"version":"v4_detail_conflict"}},
               {"turn_index":2,"excerpt":"f","evidence_check":{"status":"checked",
               "claims":[{"claim":"c","label":"CONFLICTING","reason":"r","citations":[{"fact_id":"a1","content":"x","citation":null,"stance":"contradicts"}]}],
               "counts":{"CONFLICTING":1},"evidence_score_before":4,"evidence_score_after":4,"rule_applied":"khong doi","error":null,"version":"v4_detail_conflict"}}],
             "evidence_score_before":4,"evidence_score_after":4,"evidence_rule_applied":"khong doi"}
            """;

            var round = JsonSerializer.Deserialize<EvaluateRoundResponse>(json)!;

            Assert.Equal(2, round.EvidenceChecks!.Count);
            Assert.Equal("no_fact_base", round.EvidenceChecks[0].EvidenceCheck.Status);
            var check = round.EvidenceChecks[1];
            Assert.Equal(2, check.TurnIndex);
            Assert.Equal("CONFLICTING", check.EvidenceCheck.Claims![0].Label);
            Assert.Equal("contradicts", check.EvidenceCheck.Claims[0].Citations![0].Stance);
            Assert.Equal(1, check.EvidenceCheck.Counts!["CONFLICTING"]);
            Assert.Equal("v4_detail_conflict", check.EvidenceCheck.Version);
            Assert.Equal("khong doi", round.EvidenceRuleApplied);
        }

        [Fact]
        public async Task OldJudgementWithoutEvidence_MapsWithoutError()
        {
            int sessionId = await SeedAiSessionAsync("Education");
            // Dung dinh dang RawResponseJson truoc khi co RAG
            const string oldRaw = """
            {"ProSession":{"overall_score":6.5,"stage_breakdown":{"opening":6.5},"progress_trend":"on dinh","overall_strengths":["a"],
              "overall_weaknesses":[],"overall_suggestions":[],"raw_model_output":null},
             "ConSession":null,
             "ProRounds":[{"stage":"opening","round_score":6.5,"criteria":[{"name":"Evidence","score":3,"reasoning":"r"}],
              "consistency_note":"n","strengths":[],"weaknesses":[],"suggestions":[]}],
             "ConRounds":[]}
            """;
            using (var context = _harness.CreateContext())
            {
                context.AIJudgements.Add(new AIJudgement { DebateSessionId = sessionId, SuggestedWinnerSide = "PRO", RawResponseJson = oldRaw });
                context.SaveChanges();
            }

            var result = ApiResponseAssert.Succeeds(await _harness.NewService().GetSessionEvaluationAsync(UserA, sessionId));

            var round = Assert.Single(result.ProEvaluation!.RoundEvaluations);
            Assert.Equal(6.5m, round.RoundScore);
            Assert.Null(round.EvidenceChecks);
            Assert.Null(round.EvidenceScoreBefore);
            Assert.Null(round.EvidenceRuleApplied);
            Assert.Null(result.ConEvaluation);
        }

        [Theory]
        [InlineData("Education", "education")]
        [InlineData("Chính trị", null)]
        public async Task SessionDetails_ExposeEvidenceTopic(string category, string? expected)
        {
            int sessionId = await SeedAiSessionAsync(category);

            var session = ApiResponseAssert.Succeeds(await _harness.NewService().GetSessionDetailsAsync(UserA, sessionId));

            Assert.Equal(expected, session.EvidenceTopic);
        }

        [Theory]
        [InlineData("Education", "education")]
        [InlineData("Lịch sử", null)]
        [InlineData("", null)]
        public void MapEvidenceTopic_OnlyKnownTopics(string category, string? expected)
        {
            Assert.Equal(expected, DebateService.MapEvidenceTopic(category));
        }

        private async Task<int> SeedAiSessionAsync(string? category, DebateSide userSide = DebateSide.PRO,
            RoundType? conSkips = null, bool completed = false)
        {
            int sessionId = await _harness.StartAiSessionAsync(userSide);
            SeedRoundsAndTopic(sessionId, category, conSkips, completed);
            return sessionId;
        }

        [Fact]
        public async Task ConcurrentRequests_OnOneSession_EvaluateOnce_OneJudgement()
        {
            int sessionId = await SeedAiSessionAsync("Education", completed: true);
            var client = new FakeEvaluatorClient(_ => 300);

            // 2 x GET /evaluation + 1 x POST /evaluate at the same time, each on its own service (= request scope)
            var results = await Task.WhenAll(
                _harness.NewService(client).GetSessionEvaluationAsync(UserA, sessionId),
                _harness.NewService(client).EvaluateSessionAsync(UserA, sessionId),
                _harness.NewService(client).GetSessionEvaluationAsync(UserA, sessionId));

            Assert.All(results, r => Assert.True(r.Success, r.Message));
            Assert.Equal(6, client.RoundRequests.Count);  // 1 evaluation = 3 rounds x 2 sides
            Assert.Equal(2, client.SessionRequests.Count);
            Assert.Equal(1, JudgementCount(sessionId));
            Assert.Single(results.Select(r => r.Data!.JudgementId).Distinct());
            Assert.False(_harness.Coordinator.IsRunning(sessionId));
        }

        [Fact]
        public async Task ExistingJudgement_IsReturned_WithoutCallingTheEvaluator()
        {
            int sessionId = await SeedAiSessionAsync("Education", completed: true);
            var first = ApiResponseAssert.Succeeds(await _harness.NewService(new FakeEvaluatorClient()).EvaluateSessionAsync(UserA, sessionId));
            var client = new FakeEvaluatorClient();

            var again = ApiResponseAssert.Succeeds(await _harness.NewService(client).EvaluateSessionAsync(UserA, sessionId));

            Assert.Empty(client.RoundRequests);
            Assert.Equal(first.JudgementId, again.JudgementId);
            Assert.Equal(1, JudgementCount(sessionId));
        }

        [Fact]
        public async Task FailedEvaluation_FreesTheSession_ForTheNextRequest()
        {
            int sessionId = await SeedAiSessionAsync("Education", completed: true);

            Assert.False((await _harness.NewService(new FakeEvaluatorClient { FailStage = "closing" }).EvaluateSessionAsync(UserA, sessionId)).Success);
            Assert.False(_harness.Coordinator.IsRunning(sessionId));

            ApiResponseAssert.Succeeds(await _harness.NewService(new FakeEvaluatorClient()).GetSessionEvaluationAsync(UserA, sessionId));
            Assert.Equal(1, JudgementCount(sessionId));
        }

        [Theory]
        [InlineData(false)]
        [InlineData(true)] // /evaluate/session returned nothing: the fallback average follows the same rule
        public async Task SkippedStage_CountsZero_AndRoundNumbersFollowTheStage(bool sessionReturnsNull)
        {
            int sessionId = await SeedAiSessionAsync("Education", conSkips: RoundType.REBUTTAL);
            var client = new FakeEvaluatorClient { SessionReturnsNull = sessionReturnsNull };

            var result = ApiResponseAssert.Succeeds(await _harness.NewService(client).EvaluateSessionAsync(UserA, sessionId));

            if (!sessionReturnsNull)
            {
                var conRequest = client.SessionRequests.Single(s => s.Side == "con");
                Assert.Equal(new[] { "rebuttal" }, conRequest.SkippedStages);
                Assert.Equal(new[] { "opening", "closing" }, conRequest.Rounds.Select(r => r.Stage));
                Assert.Empty(client.SessionRequests.Single(s => s.Side == "pro").SkippedStages!);
                Assert.Contains("\"skipped_stages\":[\"rebuttal\"]", JsonSerializer.Serialize(conRequest));
                Assert.Equal(new[] { "rebuttal" }, result.ConEvaluation!.SkippedStages);
                Assert.Equal(new[] { 1, 3 }, result.ConEvaluation.RoundEvaluations.Select(r => r.RoundNumber));
            }
            // Every round scores FakeEvaluatorClient.RoundScore (7): (7 + 0 + 7) / 3, like the FE: a stage without a
            // speech is a 0, not left out of the average
            Assert.Equal(7.0m, FakeEvaluatorClient.RoundScore);
            Assert.Equal(Math.Round(2 * FakeEvaluatorClient.RoundScore / 3, 2), Math.Round(result.OverallScoreCon!.Value, 2));
            Assert.Equal(4.67m, Math.Round(result.OverallScoreCon!.Value, 2));
            Assert.Equal(FakeEvaluatorClient.RoundScore, result.OverallScorePro);
            if (!sessionReturnsNull)
            {
                Assert.All(result.ConEvaluation!.RoundEvaluations, r => Assert.Equal(FakeEvaluatorClient.RoundScore, r.RoundScore));
            }
        }

        [Fact]
        public async Task CancelledWaiter_DoesNotCancelTheSharedEvaluation()
        {
            int sessionId = await SeedAiSessionAsync("Education", completed: true);
            var client = new FakeEvaluatorClient(_ => 300);
            using var gaveUp = new CancellationTokenSource();

            var cancelled = _harness.NewService(client).GetSessionEvaluationAsync(UserA, sessionId, gaveUp.Token);
            var patient = _harness.NewService(client).GetSessionEvaluationAsync(UserA, sessionId);
            gaveUp.Cancel();

            Assert.False((await cancelled).Success);  // this caller stopped waiting
            ApiResponseAssert.Succeeds(await patient); // the evaluation went on for the other one
            Assert.Equal(6, client.RoundRequests.Count);
            Assert.Equal(1, JudgementCount(sessionId));
        }

        [Fact]
        public async Task WithAScopeFactory_TheEvaluationRunsInItsOwnScope_AndSurvivesTheStarterGoingAway()
        {
            int sessionId = await SeedAiSessionAsync("Education", completed: true);
            var client = new FakeEvaluatorClient(_ => 300);
            int scopesCreated = 0;
            DebateEvaluationCoordinator coordinator = null!;
            var services = new ServiceCollection();
            services.AddScoped<IDebateService>(_ =>
            {
                Interlocked.Increment(ref scopesCreated);
                var context = _harness.CreateContext(); // disposed with the evaluation's scope
                return new DebateService(new DebateRepository(context), new UserRepository(context), client, null, coordinator);
            });
            await using var provider = services.BuildServiceProvider();
            coordinator = new DebateEvaluationCoordinator(provider.GetRequiredService<IServiceScopeFactory>());

            // The starting request: its DbContext goes away (request ended, client gone) right after it started
            var starterContext = _harness.CreateContext();
            using var gone = new CancellationTokenSource();
            var starter = new DebateService(new DebateRepository(starterContext), new UserRepository(starterContext), client, null, coordinator)
                .GetSessionEvaluationAsync(UserA, sessionId, gone.Token);
            await WaitUntilAsync(() => coordinator.IsRunning(sessionId));
            gone.Cancel();
            await starter;
            await starterContext.DisposeAsync();

            var otherContext = _harness.CreateContext();
            var result = await new DebateService(new DebateRepository(otherContext), new UserRepository(otherContext), client, null, coordinator)
                .GetSessionEvaluationAsync(UserA, sessionId);

            ApiResponseAssert.Succeeds(result);
            Assert.Equal(1, scopesCreated);
            Assert.Equal(6, client.RoundRequests.Count);
            Assert.Equal(1, JudgementCount(sessionId));
            await otherContext.DisposeAsync();
        }

        private static async Task WaitUntilAsync(Func<bool> condition)
        {
            for (int i = 0; i < 200 && !condition(); i++)
            {
                await Task.Delay(10);
            }
            Assert.True(condition(), "Timed out waiting for the evaluation to start");
        }

        private int JudgementCount(int sessionId)
        {
            using var context = _harness.CreateContext();
            return context.AIJudgements.Count(j => j.DebateSessionId == sessionId);
        }

        private async Task<int> SeedP2pSessionAsync(string? category)
        {
            int sessionId = await _harness.StartP2pSessionAsync(DebateSide.PRO);
            SeedRoundsAndTopic(sessionId, category);
            return sessionId;
        }

        // 3 round, moi round 1 luot moi phe (thay the luot da co de so luot co dinh); conSkips: round CON khong noi
        private void SeedRoundsAndTopic(int sessionId, string? category, RoundType? conSkips = null, bool completed = false)
        {
            using var context = _harness.CreateContext();
            var session = context.DebateSessions
                .Include(s => s.Topic)
                .Include(s => s.Participants)
                .Include(s => s.DebateRounds).ThenInclude(r => r.Arguments)
                .Single(s => s.DebateSessionId == sessionId);
            session.Topic!.Category = category;
            if (completed) session.Status = SessionStatus.Completed;

            context.Arguments.RemoveRange(session.DebateRounds.SelectMany(r => r.Arguments));
            var pro = session.Participants.Single(p => p.Side == DebateSide.PRO);
            var con = session.Participants.Single(p => p.Side == DebateSide.CON);
            var types = new[] { RoundType.OPENING, RoundType.REBUTTAL, RoundType.CLOSING };
            var start = DateTime.UtcNow;
            for (int i = 0; i < types.Length; i++)
            {
                var round = session.DebateRounds.FirstOrDefault(r => r.RoundNumber == i + 1);
                if (round == null)
                {
                    round = new DebateRound { DebateSessionId = sessionId, RoundNumber = i + 1 };
                    session.DebateRounds.Add(round);
                }
                round.RoundType = types[i];
                round.Arguments.Add(new Argument { ParticipantId = pro.ParticipantId, Content = $"pro {i}", SubmittedAt = start.AddMinutes(i * 2) });
                if (types[i] != conSkips)
                    round.Arguments.Add(new Argument { ParticipantId = con.ParticipantId, Content = $"con {i}", SubmittedAt = start.AddMinutes(i * 2 + 1) });
            }
            context.SaveChanges();
        }

        private string StoredRawJson(int sessionId)
        {
            using var context = _harness.CreateContext();
            return context.AIJudgements.Where(j => j.DebateSessionId == sessionId).OrderByDescending(j => j.CreatedAt).First().RawResponseJson!;
        }

        internal sealed class FakeEvaluatorClient : IAiEvaluatorClient
        {
            private readonly Func<string, int> _delayMsByStage;
            private int _activeRounds, _activeSessions;

            public FakeEvaluatorClient(Func<string, int>? delayMsByStage = null)
            {
                _delayMsByStage = delayMsByStage ?? (_ => 50);
            }

            public bool WithEvidence { get; init; }
            public string? FailStage { get; init; }
            public string? NullStage { get; init; }
            public ConcurrentQueue<EvaluateRoundRequest> RoundRequestQueue { get; } = new();
            public List<EvaluateRoundRequest> RoundRequests => RoundRequestQueue.ToList();
            public ConcurrentQueue<EvaluateSessionRequest> SessionRequestQueue { get; } = new();
            public List<EvaluateSessionRequest> SessionRequests => SessionRequestQueue.ToList();
            public int MaxConcurrentRounds { get; private set; }
            public int MaxConcurrentSessions { get; private set; }
            private readonly object _lock = new();

            public async Task<EvaluateRoundResponse?> EvaluateRoundAsync(EvaluateRoundRequest req, CancellationToken ct = default)
            {
                RoundRequestQueue.Enqueue(req);
                Track(ref _activeRounds, +1, isRound: true);
                // Doi cho moi round deu bat dau (song song) roi moi tra ve theo do tre cua stage
                await Task.Delay(100 + _delayMsByStage(req.Stage), ct);
                Track(ref _activeRounds, -1, isRound: true);
                if (req.Stage == FailStage) throw new HttpRequestException("AI Evaluator returned 500");
                if (req.Stage == NullStage) return null;

                List<TurnEvidenceCheckDto>? checks = null;
                if (WithEvidence)
                {
                    checks = new()
                    {
                        new TurnEvidenceCheckDto(0, $"{req.Side}-{req.Stage}", new EvidenceCheckSummaryDto(
                            Status: "unavailable",
                            Claims: new() { new EvidenceClaimDto("claim", "CONTRADICTED", "reason", new() { new EvidenceCitationDto("fact-1", "noi dung", "nguon", "contradicts") }) },
                            Counts: new() { ["CONTRADICTED"] = 1 },
                            EvidenceScoreBefore: 4, EvidenceScoreAfter: 3, RuleApplied: "rule",
                            Error: "TimeoutError: verify qua 20 s", Version: "v4_detail_conflict"))
                    };
                }
                return new EvaluateRoundResponse(req.Stage, RoundScore, new() { new CriterionScoreDto("Evidence", 3, "r") }, "note",
                    new(), new(), new(),
                    EvidenceChecks: checks,
                    EvidenceScoreBefore: WithEvidence ? 4 : null,
                    EvidenceScoreAfter: WithEvidence ? 3 : null,
                    EvidenceRuleApplied: WithEvidence ? $"rule-{req.Side}-{req.Stage}" : null);
            }

            public async Task<EvaluateSessionResponse?> EvaluateSessionAsync(EvaluateSessionRequest req, CancellationToken ct = default)
            {
                SessionRequestQueue.Enqueue(req);
                Track(ref _activeSessions, +1, isRound: false);
                await Task.Delay(100, ct);
                Track(ref _activeSessions, -1, isRound: false);
                if (SessionReturnsNull) return null;
                // Same formula as the Python service: every skipped stage counts 0
                var skipped = req.SkippedStages ?? new();
                var overall = Math.Round(req.Rounds.Sum(r => r.RoundScore) / (req.Rounds.Count + skipped.Count), 2);
                return new EvaluateSessionResponse(overall, req.Rounds.ToDictionary(r => r.Stage, r => r.RoundScore), "trend",
                    new(), new(), new(), SkippedStages: skipped);
            }

            public bool SessionReturnsNull { get; init; }

            /// <summary>round_score of every round this fake returns.</summary>
            public const decimal RoundScore = 7.0m;

            private void Track(ref int counter, int delta, bool isRound)
            {
                lock (_lock)
                {
                    counter += delta;
                    if (isRound) MaxConcurrentRounds = Math.Max(MaxConcurrentRounds, counter);
                    else MaxConcurrentSessions = Math.Max(MaxConcurrentSessions, counter);
                }
            }

            public Task<EvaluateArgumentResponse?> EvaluateArgumentAsync(EvaluateArgumentRequest req, CancellationToken ct = default) => throw new NotSupportedException();
            public Task<CoachingResultDto?> CoachArgumentAsync(ArgumentCoachingRequest req, CancellationToken ct = default) => throw new NotSupportedException();
            public Task<CoachingResultDto?> CoachRoundAsync(RoundCoachingRequest req, CancellationToken ct = default) => throw new NotSupportedException();
        }
    }
}
