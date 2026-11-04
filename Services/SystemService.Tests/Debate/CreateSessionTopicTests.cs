using SystemService.BLL.DTOs.Debate;
using SystemService.DAL.Entities.Debate;
using SystemService.DAL.Entities.Debate.Enums;
using static SystemService.Tests.Debate.DebateTestHarness;

namespace SystemService.Tests.Debate
{
    public class CreateSessionTopicTests : IDisposable
    {
        private readonly DebateTestHarness _harness = new();

        public void Dispose() => _harness.Dispose();

        [Fact]
        public async Task WithTopicId_UsesThatTopic_AndCreatesNoOther()
        {
            int topicId = SeedTopic("Luật AI", "AI nên được kiểm soát bởi luật quốc tế", "Hard");

            var session = ApiResponseAssert.Succeeds(await CreateAsync(topicId, title: "Luật AI", topic: "Luật AI"));

            Assert.Equal(1, TopicCount());
            Assert.Equal("Luật AI", session.Title);
            Assert.Equal("AI nên được kiểm soát bởi luật quốc tế", session.Topic);
            Assert.Equal("Hard", session.Difficulty);
        }

        [Fact]
        public async Task WithTopicId_TakesPriorityOverAMatchingTitle()
        {
            int chosen = SeedTopic("Chủ đề A", "Mô tả A");
            SeedTopic("Chủ đề B", "Mô tả B");

            var session = ApiResponseAssert.Succeeds(await CreateAsync(chosen, title: "Chủ đề B", topic: "Mô tả B"));

            Assert.Equal("Chủ đề A", session.Title);
            Assert.Equal(2, TopicCount());
        }

        [Theory]
        [InlineData(9999)]
        [InlineData(0)]
        [InlineData(-1)]
        public async Task UnknownTopicId_IsRejected_AndCreatesNothing(int topicId)
        {
            var result = await CreateAsync(topicId, title: "Luật AI", topic: "Luật AI");

            Assert.False(result.Success);
            Assert.Equal(0, TopicCount());
            Assert.Empty(ApiResponseAssert.Succeeds(await _harness.NewService().GetUserHistoryAsync(UserA)));
        }

        [Fact]
        public async Task InactiveTopic_IsRejected()
        {
            int topicId = SeedTopic("Luật AI", "Mô tả", isActive: false);

            Assert.False((await CreateAsync(topicId, title: "Luật AI", topic: "Mô tả")).Success);
        }

        [Fact]
        public async Task WithoutTopicId_DifferentTextStillCreatesATopic_AsBefore()
        {
            SeedTopic("Luật AI", "Mô tả dài");

            ApiResponseAssert.Succeeds(await CreateAsync(null, title: "Luật AI", topic: "Luật AI"));

            Assert.Equal(2, TopicCount());
        }

        [Fact]
        public async Task WithoutTopicId_SameTextReusesTheTopic_AsBefore()
        {
            SeedTopic("Luật AI", "Mô tả dài");

            ApiResponseAssert.Succeeds(await CreateAsync(null, title: "Luật AI", topic: "Mô tả dài"));

            Assert.Equal(1, TopicCount());
        }

        private Task<SystemService.BLL.Common.Responses.ApiResponse<DebateSessionResponse>> CreateAsync(int? topicId, string title, string topic)
        {
            return _harness.NewService().CreateAiPracticeSessionAsync(UserA, new CreateAiPracticeSessionRequest
            {
                TopicId = topicId,
                Title = title,
                Topic = topic,
                UserSide = DebateSide.PRO,
                IsAI = true
            });
        }

        private int SeedTopic(string title, string description, string difficulty = "Medium", bool isActive = true)
        {
            using var context = _harness.CreateContext();
            var topic = new Topic { Title = title, Description = description, Difficulty = difficulty, IsActive = isActive };
            context.Topics.Add(topic);
            context.SaveChanges();
            return topic.TopicId;
        }

        private int TopicCount()
        {
            using var context = _harness.CreateContext();
            return context.Topics.Count();
        }
    }
}
