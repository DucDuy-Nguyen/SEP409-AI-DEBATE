using System.Text.Json;
using SystemService.BLL.Common.Debate;
using SystemService.BLL.DTOs.Debate;
using SystemService.BLL.Services.Debate.Implementations;
using SystemService.BLL.Services.Debate.Interfaces;
using SystemService.DAL.Entities.Debate.Enums;
using SystemService.DAL.Entities.Identity;
using SystemService.DAL.Repositories.Debate.Implementations;
using static SystemService.Tests.Debate.DebateTestHarness;

namespace SystemService.Tests.Debate
{
    /// <summary>
    /// Team call of a 2v2 side: only between the two humans of one side, only during the preparation minute (a hangup
    /// any time), and the room is told when the minute, and so the call, ends.
    /// </summary>
    public class TeamCallTests : IDisposable
    {
        private const int UserD = 4;
        private readonly DebateTestHarness _harness = new() { Notifier = new RecordingRealtimeNotifier(), AutoEndPreparation = false };
        private readonly FakeIceServers _ice = new();

        public TeamCallTests()
        {
            using var context = _harness.CreateContext();
            context.Users.Add(new User { UserId = UserD, FullName = "Learner D", Email = "d@test.local" });
            context.SaveChanges();
        }

        public void Dispose() => _harness.Dispose();

        private TeamCallService NewTeamCall() => new(new DebateRepository(_harness.CreateContext()), _ice);

        /// <summary>A started 2v2: A + B on PRO, Outsider + D on CON, in Round 1's preparation minute.</summary>
        private async Task<int> StartHuman2v2Async()
        {
            var created = ApiResponseAssert.Succeeds(await _harness.NewService().Create2v2SessionAsync(UserA, new Create2v2SessionRequest
            {
                Title = "Motion",
                Topic = "Students should not have homework",
                Category = "education",
                UserSide = DebateSide.PRO,
                IsAI = false
            }));
            int sessionId = created.SessionId;
            ApiResponseAssert.Succeeds(await _harness.NewService().Join2v2SessionAsync(UserB, sessionId, new Join2v2SessionRequest { PreferredSide = DebateSide.PRO }));
            ApiResponseAssert.Succeeds(await _harness.NewService().Join2v2SessionAsync(Outsider, sessionId, new Join2v2SessionRequest { PreferredSide = DebateSide.CON }));
            ApiResponseAssert.Succeeds(await _harness.NewService().Join2v2SessionAsync(UserD, sessionId, new Join2v2SessionRequest { PreferredSide = DebateSide.CON }));
            ApiResponseAssert.Succeeds(await _harness.NewService().StartDebateSessionAsync(UserA, sessionId));
            return sessionId;
        }

        [Fact]
        public async Task DuringThePreparation_ASignalGoesToTheTeammateOnly()
        {
            int sessionId = await StartHuman2v2Async();

            var pro = ApiResponseAssert.Succeeds(await NewTeamCall().AuthorizeSignalAsync(UserA, sessionId, DebateTeamCall.Offer));
            Assert.Equal(new[] { UserB }, pro.TeammateUserIds);

            var con = ApiResponseAssert.Succeeds(await NewTeamCall().AuthorizeSignalAsync(UserD, sessionId, DebateTeamCall.Ice));
            Assert.Equal(new[] { Outsider }, con.TeammateUserIds);
        }

        [Fact]
        public async Task AfterThePreparation_OnlyAHangupIsRelayed()
        {
            int sessionId = await StartHuman2v2Async();
            _harness.EndPreparation(sessionId);

            ApiResponseAssert.FailsWith(await NewTeamCall().AuthorizeSignalAsync(UserA, sessionId, DebateTeamCall.Offer), DebateErrorCodes.TeamCallClosed);
            ApiResponseAssert.FailsWith(await NewTeamCall().AuthorizeSignalAsync(UserA, sessionId, DebateTeamCall.Ice), DebateErrorCodes.TeamCallClosed);
            var hangup = ApiResponseAssert.Succeeds(await NewTeamCall().AuthorizeSignalAsync(UserA, sessionId, DebateTeamCall.Hangup));
            Assert.Equal(new[] { UserB }, hangup.TeammateUserIds);
        }

        [Fact]
        public async Task BeforeTheStart_NobodyCalls()
        {
            var created = ApiResponseAssert.Succeeds(await _harness.NewService().Create2v2SessionAsync(UserA, new Create2v2SessionRequest
            {
                Title = "Motion",
                Topic = "Topic",
                Category = "education",
                UserSide = DebateSide.PRO,
                IsAI = false
            }));
            ApiResponseAssert.Succeeds(await _harness.NewService().Join2v2SessionAsync(UserB, created.SessionId, new Join2v2SessionRequest { PreferredSide = DebateSide.PRO }));

            ApiResponseAssert.FailsWith(await NewTeamCall().AuthorizeSignalAsync(UserA, created.SessionId, DebateTeamCall.Offer), DebateErrorCodes.SessionNotInProgress);
            // ...but the ICE servers may be fetched ahead, in the lobby
            ApiResponseAssert.Succeeds(await NewTeamCall().GetIceServersAsync(UserA, created.SessionId));
        }

        [Fact]
        public async Task AnOutsider_OrADebaterWithoutAHumanTeammate_CannotCall()
        {
            int teamSession = await StartHuman2v2Async();
            using (var context = _harness.CreateContext())
            {
                context.Users.Add(new User { UserId = 99, FullName = "Stranger", Email = "x@test.local" });
                context.SaveChanges();
            }
            ApiResponseAssert.FailsWith(await NewTeamCall().AuthorizeSignalAsync(99, teamSession, DebateTeamCall.Offer), DebateErrorCodes.NotParticipant);
            ApiResponseAssert.FailsWith(await NewTeamCall().GetIceServersAsync(99, teamSession), DebateErrorCodes.NotParticipant);

            // 1v1 P2P: nobody on the same side
            int p2p = await _harness.StartP2pSessionAsync(DebateSide.PRO, endPreparation: false);
            ApiResponseAssert.FailsWith(await NewTeamCall().AuthorizeSignalAsync(UserA, p2p, DebateTeamCall.Offer), DebateErrorCodes.NoTeammate);

            // AI practice: the AI is no teammate to call
            int ai = await _harness.StartAiSessionAsync(DebateSide.PRO, endPreparation: false);
            ApiResponseAssert.FailsWith(await NewTeamCall().AuthorizeSignalAsync(UserA, ai, DebateTeamCall.Offer), DebateErrorCodes.NoTeammate);

            ApiResponseAssert.FailsWith(await NewTeamCall().AuthorizeSignalAsync(UserA, 12345, DebateTeamCall.Offer), DebateErrorCodes.SessionNotFound);
            Assert.Equal(0, _ice.Calls);
        }

        [Fact]
        public async Task AnUnknownSignalType_IsRefused()
        {
            int sessionId = await StartHuman2v2Async();
            ApiResponseAssert.FailsWith(await NewTeamCall().AuthorizeSignalAsync(UserA, sessionId, "broadcast"), DebateErrorCodes.InvalidRequest);
        }

        [Fact]
        public async Task EachPreparationMinuteOfAHuman2v2_SchedulesTheEndOfTheCall()
        {
            int sessionId = await StartHuman2v2Async();

            var round1 = Assert.Single(_harness.Notifier!.TeamCallEnds);
            Assert.Equal((sessionId, 1), (round1.SessionId, round1.RoundNumber));
            Assert.Equal(_harness.LoadSession(sessionId).DebateRounds.Single(r => r.RoundNumber == 1).StartTime!.Value.Ticks, round1.EndsAt.Ticks);

            // The four speeches of Round 1, then Round 2 prepares: its call end is scheduled too
            _harness.EndPreparation(sessionId);
            foreach (var speaker in new[] { UserA, Outsider, UserB, UserD })
            {
                ApiResponseAssert.Succeeds(await _harness.NewService().SubmitArgumentAsync(speaker, sessionId, new SubmitArgumentRequest { Content = "Speech" }));
            }
            Assert.Equal(new[] { 1, 2 }, _harness.Notifier.TeamCallEnds.Select(e => e.RoundNumber));
        }

        [Fact]
        public async Task An1v1Room_SchedulesNoCall()
        {
            await _harness.StartP2pSessionAsync(DebateSide.PRO, endPreparation: false);
            await _harness.StartAiSessionAsync(DebateSide.PRO, endPreparation: false);
            Assert.Empty(_harness.Notifier!.TeamCallEnds);
        }

        [Fact]
        public async Task IceServers_ComeFromTheProvider_ForATeamDebater()
        {
            int sessionId = await StartHuman2v2Async();
            var servers = ApiResponseAssert.Succeeds(await NewTeamCall().GetIceServersAsync(UserB, sessionId));
            Assert.Equal("stun:test", Assert.Single(servers.IceServers).Urls.Single());
            Assert.Equal(1, _ice.Calls);
        }

        [Fact]
        public void CloudflareResponse_IsReadAsIceServers_WithoutPort53()
        {
            using var json = JsonDocument.Parse("""
                {"iceServers":[
                  {"urls":["stun:stun.cloudflare.com:3478","stun:stun.cloudflare.com:53"]},
                  {"urls":["turn:turn.cloudflare.com:3478?transport=udp","turn:turn.cloudflare.com:53?transport=udp","turns:turn.cloudflare.com:443?transport=tcp"],
                   "username":"u1","credential":"c1"}
                ]}
                """);

            var servers = CloudflareIceServerProvider.ParseIceServers(json.RootElement);

            Assert.Equal(2, servers.Count);
            Assert.Equal(new[] { "stun:stun.cloudflare.com:3478" }, servers[0].Urls);
            Assert.Null(servers[0].Username);
            Assert.Equal(new[] { "turn:turn.cloudflare.com:3478?transport=udp", "turns:turn.cloudflare.com:443?transport=tcp" }, servers[1].Urls);
            Assert.Equal(("u1", "c1"), (servers[1].Username, servers[1].Credential));
        }

        [Fact]
        public async Task WithoutCloudflareKeys_TheProviderGivesStunOnly()
        {
            var config = new Microsoft.Extensions.Configuration.ConfigurationBuilder().Build();
            var provider = new CloudflareIceServerProvider(new HttpClient(new NoNetworkHandler()), config);

            var servers = await provider.GetIceServersAsync();

            Assert.Equal(CloudflareIceServerProvider.DefaultStunUrl, Assert.Single(servers.IceServers).Urls.Single());
            Assert.Equal(0, servers.TtlSeconds);
        }

        private sealed class FakeIceServers : IIceServerProvider
        {
            public int Calls { get; private set; }

            public Task<IceServersResponse> GetIceServersAsync(CancellationToken cancellationToken = default)
            {
                Calls++;
                return Task.FromResult(new IceServersResponse { IceServers = new() { new IceServerDto { Urls = new() { "stun:test" } } } });
            }
        }

        private sealed class NoNetworkHandler : HttpMessageHandler
        {
            protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken) =>
                throw new InvalidOperationException("No network call expected.");
        }
    }
}
