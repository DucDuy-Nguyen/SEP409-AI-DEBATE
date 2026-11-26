using SystemService.BLL.Common.Debate;
using SystemService.BLL.DTOs.Debate;
using SystemService.BLL.Services.Debate.Implementations;
using SystemService.DAL.Entities.Debate.Enums;
using SystemService.DAL.Repositories.Debate.Implementations;
using static SystemService.Tests.Debate.DebateTestHarness;

namespace SystemService.Tests.Debate
{
    /// <summary>Every topic and session tells PRO and CON what they have to do: the topic's own text, else a generic one.</summary>
    public class TopicSideGuideTests : IDisposable
    {
        private readonly DebateTestHarness _harness = new();

        public void Dispose() => _harness.Dispose();

        [Fact]
        public async Task ATopicWithoutGuides_GetsTheGenericTexts_WithItsTitle()
        {
            var created = ApiResponseAssert.Succeeds(await NewTopicService().CreateTopicAsync(UserA,
                new CreateTopicRequest { Title = "Cấm điện thoại trong lớp", Category = "education", ProGuide = "   " }));

            Assert.False(created.HasCustomGuides);
            Assert.Equal(DebateSideGuide.Generic("Cấm điện thoại trong lớp", DebateSide.PRO), created.ProGuide);
            Assert.Equal(DebateSideGuide.Generic("Cấm điện thoại trong lớp", DebateSide.CON), created.ConGuide);
            Assert.Contains("Cấm điện thoại trong lớp", created.ProGuide);
            Assert.NotEqual(created.ProGuide, created.ConGuide);
        }

        [Fact]
        public async Task CustomGuides_AreKept_UpdatedWhenSent_AndClearedByAnEmptyString()
        {
            var service = NewTopicService();
            var created = ApiResponseAssert.Succeeds(await service.CreateTopicAsync(UserA, new CreateTopicRequest
            {
                Title = "Học online", Category = "education", ProGuide = "  Chứng minh học online hiệu quả  ", ConGuide = "Chỉ ra hạn chế",
            }));
            Assert.True(created.HasCustomGuides);
            Assert.Equal(("Chứng minh học online hiệu quả", "Chỉ ra hạn chế"), (created.ProGuide, created.ConGuide));

            // null keeps the text
            var kept = ApiResponseAssert.Succeeds(await service.UpdateTopicAsync(created.TopicId, new UpdateTopicRequest { Difficulty = "Hard" }));
            Assert.Equal(("Chứng minh học online hiệu quả", "Chỉ ra hạn chế"), (kept.ProGuide, kept.ConGuide));

            var changed = ApiResponseAssert.Succeeds(await service.UpdateTopicAsync(created.TopicId, new UpdateTopicRequest { ConGuide = "Mới" }));
            Assert.Equal("Mới", changed.ConGuide);

            var cleared = ApiResponseAssert.Succeeds(await service.UpdateTopicAsync(created.TopicId, new UpdateTopicRequest { ProGuide = "", ConGuide = "" }));
            Assert.False(cleared.HasCustomGuides);
            Assert.Equal(DebateSideGuide.Generic("Học online", DebateSide.PRO), cleared.ProGuide);
        }

        [Fact]
        public async Task TheSession_CarriesBothGuides_ToEveryDebater()
        {
            var topic = ApiResponseAssert.Succeeds(await NewTopicService().CreateTopicAsync(UserA, new CreateTopicRequest
            {
                Title = "Học qua chơi", Category = "education", ProGuide = "Nhiệm vụ PRO",
            }));

            var session = ApiResponseAssert.Succeeds(await _harness.NewService().CreateP2pSessionAsync(UserA, new CreateP2pSessionRequest
            {
                TopicId = topic.TopicId, Title = "x", Topic = "x", Category = "education", UserSide = DebateSide.PRO,
            }));
            Assert.Equal("Nhiệm vụ PRO", session.ProGuide);
            Assert.Equal(DebateSideGuide.Generic("Học qua chơi", DebateSide.CON), session.ConGuide);

            var details = ApiResponseAssert.Succeeds(await _harness.NewService().GetSessionDetailsAsync(UserB, session.SessionId));
            Assert.Equal((session.ProGuide, session.ConGuide), (details.ProGuide, details.ConGuide));
        }

        [Fact]
        public void AGuideOverTheLimit_FailsValidation()
        {
            var request = new UpdateTopicRequest { ProGuide = new string('a', DebateSideGuideLimits.MaxLength + 1) };
            var results = new List<System.ComponentModel.DataAnnotations.ValidationResult>();

            bool valid = System.ComponentModel.DataAnnotations.Validator.TryValidateObject(
                request, new System.ComponentModel.DataAnnotations.ValidationContext(request), results, validateAllProperties: true);

            Assert.False(valid);
        }

        private TopicService NewTopicService() => new(new TopicRepository(_harness.CreateContext()));
    }
}
