using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using SystemService.BLL.Common.Responses;
using SystemService.BLL.DTOs.Debate;

namespace SystemService.BLL.Services.Debate.Interfaces
{
    public interface ITopicService
    {
        Task<ApiResponse<PagedResult<TopicDto>>> GetTopicsAsync(TopicQueryParameters query, CancellationToken cancellationToken = default);
        Task<ApiResponse<TopicDto>> GetTopicByIdAsync(int topicId, CancellationToken cancellationToken = default);
        Task<ApiResponse<TopicDto>> CreateTopicAsync(int userId, CreateTopicRequest request, CancellationToken cancellationToken = default);
        Task<ApiResponse<TopicDto>> UpdateTopicAsync(int topicId, UpdateTopicRequest request, CancellationToken cancellationToken = default);
        Task<ApiResponse<bool>> DeleteTopicAsync(int topicId, CancellationToken cancellationToken = default);
    }
}
