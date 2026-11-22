using SystemService.BLL.Common.Debate;
using SystemService.BLL.DTOs.Debate;
using SystemService.BLL.Services.Debate.Implementations;
using SystemService.DAL.Entities.Debate;
using SystemService.DAL.Entities.Debate.Enums;
using SystemService.DAL.Repositories.Debate.Implementations;
using static SystemService.Tests.Debate.DebateTestHarness;

namespace SystemService.Tests.Debate
{
    /// <summary>Every topic belongs to one of the fixed categories, stored as its code; no catch-all "General".</summary>
    public class TopicCategoryTests : IDisposable
    {
        private readonly DebateTestHarness _harness = new();

        public void Dispose() => _harness.Dispose();

        [Theory]
        [InlineData("technology", "technology")]
        [InlineData("  TECHNOLOGY ", "technology")]
        [InlineData("Công nghệ", "technology")]
        [InlineData("giáo dục", "education")]
        [InlineData("Xã hội", "society")]
        [InlineData("economy", null)]
        [InlineData("Pháp luật", null)]
        [InlineData("General", null)]
        [InlineData("Chung", null)]
        [InlineData("Môi trường", null)]
        [InlineData("", null)]
        [InlineData(null, null)]
        public void Normalize_AcceptsCodesAndVietnameseLabelsOnly(string? value, string? expected)
        {
            Assert.Equal(expected, TopicCategories.Normalize(value));
        }

        [Theory]
        [InlineData("Công nghệ", "technology")]
        [InlineData("society", "society")]
        [InlineData("economy", null)]
        [InlineData("General", null)]
        public void EvidenceTopic_OnlyForCategoriesWithAFactBase(string category, string? expected)
        {
            Assert.Equal(expected, DebateService.MapEvidenceTopic(category));
        }

        [Theory]
        [InlineData(null)]
        [InlineData("General")]
        [InlineData("Chung")]
        public async Task AiSession_FromFreeText_WithoutAValidCategory_IsRejected_AndCreatesNothing(string? category)
        {
            var res = await CreateAiAsync("Kiểm soát AI bằng luật pháp quốc tế", category);

            Assert.False(res.Success);
            Assert.Equal(TopicCategories.InvalidMessage, res.Message);
            Assert.Equal(0, Topics().Count);
        }

        [Fact]
        public async Task AiSession_FromFreeText_StoresTheCategoryCode()
        {
            ApiResponseAssert.Succeeds(await CreateAiAsync("Kiểm soát AI bằng luật pháp quốc tế", "Công nghệ"));

            Assert.Equal("technology", Assert.Single(Topics()).Category);
        }

        [Fact]
        public async Task AiSession_ReusingAGeneralTopic_GivesItTheCategory()
        {
            SeedTopic("Kiểm soát AI", "Kiểm soát AI", "General");

            ApiResponseAssert.Succeeds(await CreateAiAsync("Kiểm soát AI", "technology"));

            Assert.Equal("technology", Assert.Single(Topics()).Category);
        }

        [Fact]
        public async Task AiSession_ReusingACategorisedTopic_KeepsItsCategory()
        {
            SeedTopic("Kiểm soát AI", "Kiểm soát AI", "education");

            ApiResponseAssert.Succeeds(await CreateAiAsync("Kiểm soát AI", "technology"));

            Assert.Equal("education", Assert.Single(Topics()).Category);
        }

        [Fact]
        public async Task AiSession_WithTopicId_NeedsNoCategory()
        {
            int topicId = SeedTopic("Kiểm soát AI", "Kiểm soát AI", "technology");

            ApiResponseAssert.Succeeds(await _harness.NewService().CreateAiPracticeSessionAsync(UserA, new CreateAiPracticeSessionRequest
            {
                TopicId = topicId, Title = "x", Topic = "x", UserSide = DebateSide.PRO, IsAI = true,
            }));
        }

        [Fact]
        public async Task P2pRoom_FromFreeText_WithoutCategory_IsRejected()
        {
            var res = await _harness.NewService().CreateP2pSessionAsync(UserA, new CreateP2pSessionRequest
            {
                Title = "Motion", Topic = "Topic", UserSide = DebateSide.PRO,
            });

            Assert.False(res.Success);
            Assert.Equal(TopicCategories.InvalidMessage, res.Message);
        }

        [Fact]
        public async Task AdminCreate_WithoutCategory_IsRejected_AndWithALabel_StoresTheCode()
        {
            using var context = _harness.CreateContext();
            var service = new TopicService(new TopicRepository(context));

            var missing = await service.CreateTopicAsync(UserA, new CreateTopicRequest { Title = "A" });
            Assert.False(missing.Success);

            var created = ApiResponseAssert.Succeeds(await service.CreateTopicAsync(UserA, new CreateTopicRequest { Title = "B", Category = "Xã hội" }));
            Assert.Equal("society", created.Category);
        }

        [Fact]
        public async Task AdminUpdate_ToAnUnknownCategory_IsRejected()
        {
            int topicId = SeedTopic("A", "A", "society");
            using var context = _harness.CreateContext();
            var service = new TopicService(new TopicRepository(context));

            var res = await service.UpdateTopicAsync(topicId, new UpdateTopicRequest { Category = "General" });

            Assert.False(res.Success);
            Assert.Equal("society", Topics().Single().Category);
        }

        private Task<SystemService.BLL.Common.Responses.ApiResponse<DebateSessionResponse>> CreateAiAsync(string text, string? category)
        {
            return _harness.NewService().CreateAiPracticeSessionAsync(UserA, new CreateAiPracticeSessionRequest
            {
                Title = text, Topic = text, Category = category, UserSide = DebateSide.PRO, IsAI = true,
            });
        }

        private int SeedTopic(string title, string description, string category)
        {
            using var context = _harness.CreateContext();
            var topic = new Topic { Title = title, Description = description, Category = category, Difficulty = "Medium", IsActive = true };
            context.Topics.Add(topic);
            context.SaveChanges();
            return topic.TopicId;
        }

        private List<Topic> Topics()
        {
            using var context = _harness.CreateContext();
            return context.Topics.ToList();
        }
    }
}
