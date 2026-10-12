using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using SystemService.DAL.Entities.Debate;

namespace SystemService.DAL.Repositories.Debate.Interfaces
{
    public interface ITopicRepository
    {
        Task<(List<Topic> Items, int TotalCount)> GetTopicsAsync(
            string? searchTerm = null,
            string? category = null,
            string? difficulty = null,
            bool? isActive = true,
            int pageNumber = 1,
            int pageSize = 20,
            CancellationToken cancellationToken = default);

        Task<Topic?> GetByIdAsync(int topicId, CancellationToken cancellationToken = default);
        Task<Topic> AddAsync(Topic topic, CancellationToken cancellationToken = default);
        Task UpdateAsync(Topic topic, CancellationToken cancellationToken = default);
        Task DeleteAsync(Topic topic, CancellationToken cancellationToken = default);
        Task<bool> ExistsByTitleAsync(string title, int? excludeTopicId = null, CancellationToken cancellationToken = default);
    }
}
