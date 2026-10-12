using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using SystemService.BLL.Common.Responses;
using SystemService.BLL.DTOs.Debate;
using SystemService.BLL.Services.Debate.Interfaces;
using SystemService.DAL.Entities.Debate;
using SystemService.DAL.Repositories.Debate.Interfaces;

namespace SystemService.BLL.Services.Debate.Implementations
{
    public class TopicService : ITopicService
    {
        private readonly ITopicRepository _topicRepository;

        public TopicService(ITopicRepository topicRepository)
        {
            _topicRepository = topicRepository;
        }

        public async Task<ApiResponse<PagedResult<TopicDto>>> GetTopicsAsync(TopicQueryParameters query, CancellationToken cancellationToken = default)
        {
            var (items, totalCount) = await _topicRepository.GetTopicsAsync(
                query.SearchTerm,
                query.Category,
                query.Difficulty,
                query.IsActive,
                query.PageNumber,
                query.PageSize,
                cancellationToken);

            var pageNumber = query.PageNumber < 1 ? 1 : query.PageNumber;
            var pageSize = query.PageSize < 1 ? 20 : (query.PageSize > 100 ? 100 : query.PageSize);

            var dtos = items.Select(MapToDto).ToList();

            var pagedResult = new PagedResult<TopicDto>
            {
                Items = dtos,
                TotalCount = totalCount,
                PageNumber = pageNumber,
                PageSize = pageSize
            };

            return ApiResponse<PagedResult<TopicDto>>.SuccessResponse(pagedResult, "Topics retrieved successfully.");
        }

        public async Task<ApiResponse<TopicDto>> GetTopicByIdAsync(int topicId, CancellationToken cancellationToken = default)
        {
            var topic = await _topicRepository.GetByIdAsync(topicId, cancellationToken);
            if (topic == null)
            {
                return ApiResponse<TopicDto>.FailureResponse("Topic not found.");
            }

            return ApiResponse<TopicDto>.SuccessResponse(MapToDto(topic), "Topic details retrieved.");
        }

        public async Task<ApiResponse<TopicDto>> CreateTopicAsync(int userId, CreateTopicRequest request, CancellationToken cancellationToken = default)
        {
            var exists = await _topicRepository.ExistsByTitleAsync(request.Title, null, cancellationToken);
            if (exists)
            {
                return ApiResponse<TopicDto>.FailureResponse("A topic with this title already exists.");
            }

            var topic = new Topic
            {
                Title = request.Title.Trim(),
                Description = request.Description?.Trim(),
                Category = string.IsNullOrWhiteSpace(request.Category) ? "General" : request.Category.Trim(),
                Difficulty = string.IsNullOrWhiteSpace(request.Difficulty) ? "Medium" : request.Difficulty.Trim(),
                CreatedBy = userId,
                IsActive = true,
                CreatedAt = DateTime.UtcNow
            };

            await _topicRepository.AddAsync(topic, cancellationToken);

            var fullTopic = await _topicRepository.GetByIdAsync(topic.TopicId, cancellationToken);
            return ApiResponse<TopicDto>.SuccessResponse(MapToDto(fullTopic ?? topic), "Topic created successfully.");
        }

        public async Task<ApiResponse<TopicDto>> UpdateTopicAsync(int topicId, UpdateTopicRequest request, CancellationToken cancellationToken = default)
        {
            var topic = await _topicRepository.GetByIdAsync(topicId, cancellationToken);
            if (topic == null)
            {
                return ApiResponse<TopicDto>.FailureResponse("Topic not found.");
            }

            if (!string.IsNullOrWhiteSpace(request.Title) && !request.Title.Equals(topic.Title, StringComparison.OrdinalIgnoreCase))
            {
                var exists = await _topicRepository.ExistsByTitleAsync(request.Title, topicId, cancellationToken);
                if (exists)
                {
                    return ApiResponse<TopicDto>.FailureResponse("Another topic with this title already exists.");
                }
                topic.Title = request.Title.Trim();
            }

            if (request.Description != null)
            {
                topic.Description = request.Description.Trim();
            }

            if (!string.IsNullOrWhiteSpace(request.Category))
            {
                topic.Category = request.Category.Trim();
            }

            if (!string.IsNullOrWhiteSpace(request.Difficulty))
            {
                topic.Difficulty = request.Difficulty.Trim();
            }

            if (request.IsActive.HasValue)
            {
                topic.IsActive = request.IsActive.Value;
            }

            topic.UpdatedAt = DateTime.UtcNow;

            await _topicRepository.UpdateAsync(topic, cancellationToken);

            var updatedTopic = await _topicRepository.GetByIdAsync(topicId, cancellationToken);
            return ApiResponse<TopicDto>.SuccessResponse(MapToDto(updatedTopic ?? topic), "Topic updated successfully.");
        }

        public async Task<ApiResponse<bool>> DeleteTopicAsync(int topicId, CancellationToken cancellationToken = default)
        {
            var topic = await _topicRepository.GetByIdAsync(topicId, cancellationToken);
            if (topic == null)
            {
                return ApiResponse<bool>.FailureResponse("Topic not found.");
            }

            await _topicRepository.DeleteAsync(topic, cancellationToken);
            return ApiResponse<bool>.SuccessResponse(true, "Topic deactivated/deleted successfully.");
        }

        private static TopicDto MapToDto(Topic topic)
        {
            return new TopicDto
            {
                TopicId = topic.TopicId,
                Title = topic.Title,
                Description = topic.Description,
                Category = topic.Category,
                Difficulty = topic.Difficulty,
                CreatedBy = topic.CreatedBy,
                CreatedByUserName = topic.CreatedByUser?.FullName,
                IsActive = topic.IsActive,
                CreatedAt = topic.CreatedAt,
                UpdatedAt = topic.UpdatedAt
            };
        }
    }
}
