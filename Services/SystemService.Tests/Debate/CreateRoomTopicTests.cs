using SystemService.BLL.Common.Responses;
using SystemService.BLL.DTOs.Debate;
using SystemService.DAL.Entities.Debate;
using SystemService.DAL.Entities.Debate.Enums;
using static SystemService.Tests.Debate.DebateTestHarness;

namespace SystemService.Tests.Debate
{
    /// <summary>
    /// P2P (1v1) and 2v2 rooms take an optional TopicId like the AI practice (commit dcae510): the picked topic's
    /// Category then gives the session its evidenceTopic. Creating by title still works, without an evidence check.
    /// </summary>
    public class CreateRoomTopicTests : IDisposable
    {
        private readonly DebateTestHarness _harness = new();

        public void Dispose() => _harness.Dispose();

        public enum Room { OneVsOne, TwoVsTwo }

        [Theory]
        [InlineData(Room.OneVsOne)]
        [InlineData(Room.TwoVsTwo)]
        public async Task WithTopicId_UsesThatTopic_AndItsCategoryGivesTheEvidenceTopic(Room room)
        {
            int topicId = SeedTopic("Học qua chơi", "Học thông qua chơi nên được áp dụng rộng rãi", "Education");

            var session = ApiResponseAssert.Succeeds(await CreateAsync(room, topicId, title: "Tiêu đề khác", topic: "Mô tả khác"));

            Assert.Equal("Học qua chơi", session.Title);
            Assert.Equal("Học thông qua chơi nên được áp dụng rộng rãi", session.Topic);
            Assert.Equal("education", session.EvidenceTopic);
            Assert.Equal(1, TopicCount()); // no second topic from the other text
            var details = ApiResponseAssert.Succeeds(await _harness.NewService().GetSessionDetailsAsync(UserA, session.SessionId));
            Assert.Equal("education", details.EvidenceTopic);
        }

        [Theory]
        [InlineData(Room.OneVsOne)]
        [InlineData(Room.TwoVsTwo)]
        public async Task WithoutTopicId_CreatesByTitle_AsBefore_WithoutEvidenceTopic(Room room)
        {
            SeedTopic("Học qua chơi", "Mô tả", "Education");

            var session = ApiResponseAssert.Succeeds(await CreateAsync(room, null, title: "Phòng tự đặt", topic: "Chủ đề tự viết"));

            Assert.Null(session.EvidenceTopic);
            Assert.Equal(2, TopicCount());
        }

        [Theory]
        [InlineData(Room.OneVsOne, 9999)]
        [InlineData(Room.TwoVsTwo, 9999)]
        [InlineData(Room.OneVsOne, -1)]
        public async Task UnknownTopicId_IsRejected_AndCreatesNothing(Room room, int topicId)
        {
            var result = await CreateAsync(room, topicId, title: "x", topic: "x");

            Assert.False(result.Success);
            Assert.Equal(0, TopicCount());
            Assert.Empty(ApiResponseAssert.Succeeds(await _harness.NewService().GetUserHistoryAsync(UserA)));
        }

        [Fact]
        public async Task InactiveTopic_IsRejected()
        {
            int topicId = SeedTopic("Cũ", "Mô tả", "Education", isActive: false);

            Assert.False((await CreateAsync(Room.OneVsOne, topicId, title: "Cũ", topic: "Mô tả")).Success);
            Assert.False((await CreateAsync(Room.TwoVsTwo, topicId, title: "Cũ", topic: "Mô tả")).Success);
        }

        private Task<ApiResponse<DebateSessionResponse>> CreateAsync(Room room, int? topicId, string title, string topic)
        {
            return room == Room.OneVsOne
                ? _harness.NewService().CreateP2pSessionAsync(UserA, new CreateP2pSessionRequest
                {
                    TopicId = topicId, Title = title, Topic = topic, UserSide = DebateSide.PRO,
                })
                : _harness.NewService().Create2v2SessionAsync(UserA, new Create2v2SessionRequest
                {
                    TopicId = topicId, Title = title, Topic = topic, UserSide = DebateSide.PRO,
                });
        }

        private int SeedTopic(string title, string description, string? category, bool isActive = true)
        {
            using var context = _harness.CreateContext();
            var topic = new Topic { Title = title, Description = description, Category = category, IsActive = isActive };
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
