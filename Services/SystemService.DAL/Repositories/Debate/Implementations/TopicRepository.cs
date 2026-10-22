using Microsoft.EntityFrameworkCore;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using SystemService.DAL.Context;
using SystemService.DAL.Entities.Debate;
using SystemService.DAL.Repositories.Debate.Interfaces;

namespace SystemService.DAL.Repositories.Debate.Implementations
{
    public class TopicRepository : ITopicRepository
    {
        private readonly SystemDbContext _context;

        public TopicRepository(SystemDbContext context)
        {
            _context = context;
        }

        public async Task<(List<Topic> Items, int TotalCount)> GetTopicsAsync(
            string? searchTerm = null,
            string? category = null,
            string? difficulty = null,
            bool? isActive = true,
            int pageNumber = 1,
            int pageSize = 20,
            CancellationToken cancellationToken = default)
        {
            var dbQuery = _context.Topics
                .Include(t => t.CreatedByUser)
                .AsNoTracking()
                .AsQueryable();

            if (isActive.HasValue)
            {
                dbQuery = dbQuery.Where(t => t.IsActive == isActive.Value);
            }

            if (!string.IsNullOrWhiteSpace(searchTerm))
            {
                var term = searchTerm.Trim().ToLower();
                dbQuery = dbQuery.Where(t => t.Title.ToLower().Contains(term) || (t.Description != null && t.Description.ToLower().Contains(term)));
            }

            if (!string.IsNullOrWhiteSpace(category))
            {
                var cat = category.Trim().ToLower();
                dbQuery = dbQuery.Where(t => t.Category != null && t.Category.ToLower() == cat);
            }

            if (!string.IsNullOrWhiteSpace(difficulty))
            {
                var diff = difficulty.Trim().ToLower();
                dbQuery = dbQuery.Where(t => t.Difficulty.ToLower() == diff);
            }

            int totalCount = await dbQuery.CountAsync(cancellationToken);

            int page = pageNumber < 1 ? 1 : pageNumber;
            int size = pageSize < 1 ? 20 : (pageSize > 100 ? 100 : pageSize);

            var items = await dbQuery
                .OrderByDescending(t => t.CreatedAt)
                .Skip((page - 1) * size)
                .Take(size)
                .ToListAsync(cancellationToken);

            return (items, totalCount);
        }

        public async Task<Topic?> GetByIdAsync(int topicId, CancellationToken cancellationToken = default)
        {
            return await _context.Topics
                .Include(t => t.CreatedByUser)
                .FirstOrDefaultAsync(t => t.TopicId == topicId, cancellationToken);
        }

        public async Task<Topic> AddAsync(Topic topic, CancellationToken cancellationToken = default)
        {
            await _context.Topics.AddAsync(topic, cancellationToken);
            await _context.SaveChangesAsync(cancellationToken);
            return topic;
        }

        public async Task UpdateAsync(Topic topic, CancellationToken cancellationToken = default)
        {
            _context.Topics.Update(topic);
            await _context.SaveChangesAsync(cancellationToken);
        }

        public async Task DeleteAsync(Topic topic, CancellationToken cancellationToken = default)
        {
            topic.IsActive = false;
            topic.UpdatedAt = DateTime.UtcNow;
            _context.Topics.Update(topic);
            await _context.SaveChangesAsync(cancellationToken);
        }

        public async Task<bool> ExistsByTitleAsync(string title, int? excludeTopicId = null, CancellationToken cancellationToken = default)
        {
            var cleanTitle = title.Trim().ToLower();
            return await _context.Topics
                .AnyAsync(t => t.Title.ToLower() == cleanTitle && (!excludeTopicId.HasValue || t.TopicId != excludeTopicId.Value), cancellationToken);
        }

        public async Task<int> GetTotalTopicsCountAsync(CancellationToken cancellationToken = default)
        {
            return await _context.Topics.CountAsync(cancellationToken);
        }
    }
}
