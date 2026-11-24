using System;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using SystemService.BLL.Common.Responses;
using SystemService.BLL.DTOs.KnowledgeBase;

namespace SystemService.BLL.Services.KnowledgeBase.Interfaces
{
    public interface IKnowledgeBaseService
    {
        Task<(int StatusCode, ApiResponse<JsonElement> Body)> GetStatsAsync(CancellationToken cancellationToken = default);

        Task<(int StatusCode, ApiResponse<JsonElement> Body)> ListSourcesAsync(
            string? topic, int page, int pageSize, CancellationToken cancellationToken = default);

        Task<(int StatusCode, ApiResponse<JsonElement> Body)> CreateSourceAsync(
            CreateKnowledgeSourceRequest request, CancellationToken cancellationToken = default);

        Task<(int StatusCode, ApiResponse<JsonElement> Body)> DeleteSourceAsync(
            Guid sourceId, CancellationToken cancellationToken = default);

        Task<(int StatusCode, ApiResponse<JsonElement> Body)> ListFactsAsync(
            string? topic, string? status, Guid? sourceId, string? q, int page, int pageSize, CancellationToken cancellationToken = default);

        Task<(int StatusCode, ApiResponse<JsonElement> Body)> UpdateFactAsync(
            Guid factId, UpdateFactRequest request, CancellationToken cancellationToken = default);

        Task<(int StatusCode, ApiResponse<JsonElement> Body)> UpdateFactStatusAsync(
            Guid factId, UpdateFactStatusRequest request, CancellationToken cancellationToken = default);

        Task<(int StatusCode, ApiResponse<JsonElement> Body)> BatchUpdateFactStatusAsync(
            BatchUpdateFactStatusRequest request, CancellationToken cancellationToken = default);

        Task<(int StatusCode, ApiResponse<JsonElement> Body)> DeleteFactAsync(
            Guid factId, CancellationToken cancellationToken = default);
    }
}

