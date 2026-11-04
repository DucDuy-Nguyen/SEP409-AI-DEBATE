using SystemService.BLL.DTOs.Debate;
using SystemService.DAL.Entities.Debate;
using SystemService.DAL.Entities.Debate.Enums;
using static SystemService.Tests.Debate.DebateTestHarness;

namespace SystemService.Tests.Debate
{
    public class SessionDifficultyTests : IDisposable
    {
        private readonly DebateTestHarness _harness = new();

        public void Dispose() => _harness.Dispose();

        [Fact]
        public async Task ChosenDifficulty_WinsOverTheTopics_InEveryResponse()
        {
            int topicId = SeedTopic("Medium");

            var created = ApiResponseAssert.Succeeds(await CreateAsync(topicId, "Hard"));
            var started = ApiResponseAssert.Succeeds(await _harness.NewService().StartDebateSessionAsync(UserA, created.SessionId));
            var submitted = ApiResponseAssert.Succeeds(await _harness.UserSubmitsAsync(UserA, created.SessionId));
            var details = ApiResponseAssert.Succeeds(await _harness.NewService().GetSessionDetailsAsync(UserA, created.SessionId));

            Assert.Equal("Hard", created.Difficulty);
            Assert.Equal("Hard", started.Difficulty);
            Assert.Equal("Hard", submitted.Difficulty);
            Assert.Equal("Hard", details.Difficulty);
            Assert.Equal("Hard", _harness.LoadSession(created.SessionId).Difficulty);
        }

        [Fact]
        public async Task EachSessionKeepsItsOwnDifficulty_OnTheSameTopic()
        {
            int topicId = SeedTopic("Medium");

            var easy = ApiResponseAssert.Succeeds(await CreateAsync(topicId, "Easy"));
            var hard = ApiResponseAssert.Succeeds(await CreateAsync(topicId, "Hard"));

            Assert.Equal("Easy", ApiResponseAssert.Succeeds(await _harness.NewService().GetSessionDetailsAsync(UserA, easy.SessionId)).Difficulty);
            Assert.Equal("Hard", ApiResponseAssert.Succeeds(await _harness.NewService().GetSessionDetailsAsync(UserA, hard.SessionId)).Difficulty);
        }

        [Fact]
        public async Task SameTextLookup_KeepsTheChosenDifficulty_AndDoesNotChangeTheTopic()
        {
            ApiResponseAssert.Succeeds(await CreateAsync(null, "Easy"));

            var second = ApiResponseAssert.Succeeds(await CreateAsync(null, "Hard"));

            Assert.Equal("Hard", second.Difficulty);
            using var context = _harness.CreateContext();
            Assert.Equal("Easy", context.Topics.Single().Difficulty);
        }

        [Theory]
        [InlineData(null)]
        [InlineData("")]
        [InlineData("   ")]
        public async Task NothingChosen_FallsBackToTheTopic(string? difficulty)
        {
            int topicId = SeedTopic("Hard");

            var created = ApiResponseAssert.Succeeds(await CreateAsync(topicId, difficulty));

            Assert.Equal("Hard", created.Difficulty);
            Assert.Null(_harness.LoadSession(created.SessionId).Difficulty);
        }

        [Fact]
        public async Task WithoutTopicIdOrDifficulty_ANewTopicStillGetsMedium()
        {
            var created = ApiResponseAssert.Succeeds(await CreateAsync(null, null));

            Assert.Equal("Medium", created.Difficulty);
        }

        [Fact]
        public async Task ValueIsTrimmed()
        {
            var created = ApiResponseAssert.Succeeds(await CreateAsync(SeedTopic("Medium"), "  Hard "));

            Assert.Equal("Hard", _harness.LoadSession(created.SessionId).Difficulty);
        }

        [Fact]
        public async Task NonAiSession_FromTheSameEndpoint_DoesNotStoreIt()
        {
            int topicId = SeedTopic("Medium");

            var created = ApiResponseAssert.Succeeds(await CreateAsync(topicId, "Hard", isAi: false));

            Assert.Null(_harness.LoadSession(created.SessionId).Difficulty);
            Assert.Equal("Medium", created.Difficulty);
        }

        private Task<SystemService.BLL.Common.Responses.ApiResponse<DebateSessionResponse>> CreateAsync(int? topicId, string? difficulty, bool isAi = true)
        {
            return _harness.NewService().CreateAiPracticeSessionAsync(UserA, new CreateAiPracticeSessionRequest
            {
                TopicId = topicId,
                Title = "Luật AI",
                Topic = "Mô tả",
                UserSide = DebateSide.PRO,
                IsAI = isAi,
                Difficulty = difficulty
            });
        }

        private int SeedTopic(string difficulty)
        {
            using var context = _harness.CreateContext();
            var topic = new Topic { Title = "Luật AI", Description = "Mô tả", Difficulty = difficulty, IsActive = true };
            context.Topics.Add(topic);
            context.SaveChanges();
            return topic.TopicId;
        }
    }
}
