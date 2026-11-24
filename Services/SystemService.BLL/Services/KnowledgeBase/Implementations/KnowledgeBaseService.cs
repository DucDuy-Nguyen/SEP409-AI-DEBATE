using System;
using System.Collections.Generic;
using System.Net;
using System.Net.Http;
using System.Net.Http.Json;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.Logging;
using SystemService.BLL.Common.Debate;
using SystemService.BLL.Common.Responses;
using SystemService.BLL.DTOs.KnowledgeBase;
using SystemService.BLL.Services.KnowledgeBase.Interfaces;

namespace SystemService.BLL.Services.KnowledgeBase.Implementations
{
    public class KnowledgeBaseService : IKnowledgeBaseService
    {
        public const string EvaluatorKbClientName = "KnowledgeBaseEvaluatorClient";

        private static readonly HashSet<string> ValidStatuses = new(StringComparer.OrdinalIgnoreCase)
        {
            "pending",
            "approved",
            "rejected"
        };

        private static readonly JsonSerializerOptions SnakeJson = new()
        {
            PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
            DefaultIgnoreCondition = System.Text.Json.Serialization.JsonIgnoreCondition.WhenWritingNull
        };

        private readonly IHttpClientFactory _httpClientFactory;
        private readonly ILogger<KnowledgeBaseService> _logger;

        public KnowledgeBaseService(
            IHttpClientFactory httpClientFactory,
            ILogger<KnowledgeBaseService> logger)
        {
            _httpClientFactory = httpClientFactory;
            _logger = logger;
        }

        public Task<(int StatusCode, ApiResponse<JsonElement> Body)> GetStatsAsync(CancellationToken cancellationToken = default)
            => ForwardAsync(HttpMethod.Get, "rag/knowledge-base/stats", null, cancellationToken);

        public Task<(int StatusCode, ApiResponse<JsonElement> Body)> ListSourcesAsync(
            string? topic, int page, int pageSize, CancellationToken cancellationToken = default)
        {
            string? normalizedTopic = null;
            if (!string.IsNullOrWhiteSpace(topic))
            {
                normalizedTopic = TopicCategories.Normalize(topic);
                if (normalizedTopic == null)
                {
                    return Task.FromResult(BadRequest(TopicCategories.InvalidMessage));
                }
            }

            var qs = $"page={Math.Max(1, page)}&page_size={Math.Clamp(pageSize, 1, 100)}";
            if (normalizedTopic != null)
            {
                qs += $"&topic={Uri.EscapeDataString(normalizedTopic)}";
            }
            return ForwardAsync(HttpMethod.Get, $"rag/knowledge-base/sources?{qs}", null, cancellationToken);
        }

        public Task<(int StatusCode, ApiResponse<JsonElement> Body)> CreateSourceAsync(
            CreateKnowledgeSourceRequest request, CancellationToken cancellationToken = default)
        {
            var normalizedTopic = TopicCategories.Normalize(request.Topic);
            if (normalizedTopic == null)
            {
                return Task.FromResult(BadRequest(TopicCategories.InvalidMessage));
            }

            var payload = new
            {
                topic = normalizedTopic,
                source_type = request.SourceType,
                title = request.Title,
                url = request.Url,
                citation = request.Citation,
                published_date = request.PublishedDate?.ToString("yyyy-MM-dd"),
                raw_text = request.RawText,
                facts = request.Facts,
                auto_approve = request.AutoApprove,
                chunk_sentences = request.ChunkSentences,
                chunk_overlap = request.ChunkOverlap
            };

            return ForwardAsync(HttpMethod.Post, "rag/knowledge-base/sources", payload, cancellationToken);
        }

        public Task<(int StatusCode, ApiResponse<JsonElement> Body)> DeleteSourceAsync(
            Guid sourceId, CancellationToken cancellationToken = default)
            => ForwardAsync(HttpMethod.Delete, $"rag/knowledge-base/sources/{sourceId}", null, cancellationToken);

        public Task<(int StatusCode, ApiResponse<JsonElement> Body)> ListFactsAsync(
            string? topic, string? status, Guid? sourceId, string? q, int page, int pageSize, CancellationToken cancellationToken = default)
        {
            var queryParts = new List<string>
            {
                $"page={Math.Max(1, page)}",
                $"page_size={Math.Clamp(pageSize, 1, 100)}"
            };

            if (!string.IsNullOrWhiteSpace(topic))
            {
                var normalizedTopic = TopicCategories.Normalize(topic);
                if (normalizedTopic == null)
                {
                    return Task.FromResult(BadRequest(TopicCategories.InvalidMessage));
                }
                queryParts.Add($"topic={Uri.EscapeDataString(normalizedTopic)}");
            }

            if (!string.IsNullOrWhiteSpace(status))
            {
                var s = status.Trim().ToLowerInvariant();
                if (!ValidStatuses.Contains(s))
                {
                    return Task.FromResult(BadRequest("Trạng thái không hợp lệ. Chọn: pending, approved, rejected."));
                }
                queryParts.Add($"status={Uri.EscapeDataString(s)}");
            }

            if (sourceId.HasValue)
            {
                queryParts.Add($"source_id={sourceId.Value}");
            }

            if (!string.IsNullOrWhiteSpace(q))
            {
                queryParts.Add($"q={Uri.EscapeDataString(q.Trim())}");
            }

            return ForwardAsync(HttpMethod.Get, $"rag/knowledge-base/facts?{string.Join("&", queryParts)}", null, cancellationToken);
        }

        public Task<(int StatusCode, ApiResponse<JsonElement> Body)> UpdateFactAsync(
            Guid factId, UpdateFactRequest request, CancellationToken cancellationToken = default)
        {
            var payload = new
            {
                content = request.Content,
                citation = request.Citation,
                published_date = request.PublishedDate?.ToString("yyyy-MM-dd")
            };
            return ForwardAsync(HttpMethod.Patch, $"rag/knowledge-base/facts/{factId}", payload, cancellationToken);
        }

        public Task<(int StatusCode, ApiResponse<JsonElement> Body)> UpdateFactStatusAsync(
            Guid factId, UpdateFactStatusRequest request, CancellationToken cancellationToken = default)
        {
            var s = request.Status?.Trim().ToLowerInvariant() ?? string.Empty;
            if (!ValidStatuses.Contains(s))
            {
                return Task.FromResult(BadRequest("Trạng thái không hợp lệ. Chọn: pending, approved, rejected."));
            }
            return ForwardAsync(HttpMethod.Patch, $"rag/knowledge-base/facts/{factId}/status", new { status = s }, cancellationToken);
        }

        public Task<(int StatusCode, ApiResponse<JsonElement> Body)> BatchUpdateFactStatusAsync(
            BatchUpdateFactStatusRequest request, CancellationToken cancellationToken = default)
        {
            var s = request.Status?.Trim().ToLowerInvariant() ?? string.Empty;
            if (!ValidStatuses.Contains(s))
            {
                return Task.FromResult(BadRequest("Trạng thái không hợp lệ. Chọn: pending, approved, rejected."));
            }
            var payload = new { fact_ids = request.FactIds, status = s };
            return ForwardAsync(HttpMethod.Post, "rag/knowledge-base/facts/batch-status", payload, cancellationToken);
        }

        public Task<(int StatusCode, ApiResponse<JsonElement> Body)> DeleteFactAsync(
            Guid factId, CancellationToken cancellationToken = default)
            => ForwardAsync(HttpMethod.Delete, $"rag/knowledge-base/facts/{factId}", null, cancellationToken);

        private async Task<(int StatusCode, ApiResponse<JsonElement> Body)> ForwardAsync(
            HttpMethod method,
            string relativeUrl,
            object? payload,
            CancellationToken cancellationToken)
        {
            try
            {
                var client = _httpClientFactory.CreateClient(EvaluatorKbClientName);
                using var req = new HttpRequestMessage(method, relativeUrl);
                if (payload != null)
                {
                    req.Content = JsonContent.Create(payload, options: SnakeJson);
                }

                using var resp = await client.SendAsync(req, cancellationToken);
                var raw = await resp.Content.ReadAsStringAsync(cancellationToken);

                if (resp.IsSuccessStatusCode)
                {
                    var doc = string.IsNullOrWhiteSpace(raw)
                        ? JsonDocument.Parse("{}").RootElement
                        : JsonDocument.Parse(raw).RootElement.Clone();
                    return ((int)resp.StatusCode, ApiResponse<JsonElement>.SuccessResponse(doc, "Success"));
                }

                if (resp.StatusCode == HttpStatusCode.NotFound && relativeUrl.StartsWith("rag/knowledge-base"))
                {
                    // Could be missing item or RAG_ENABLED=false on evaluator
                    return (
                        503,
                        ApiResponse<JsonElement>.FailureResponse(
                            string.IsNullOrWhiteSpace(raw)
                                ? "AI Evaluator chưa bật RAG_ENABLED=true hoặc không tìm thấy tài nguyên."
                                : raw
                        )
                    );
                }

                return ((int)resp.StatusCode, ApiResponse<JsonElement>.FailureResponse(
                    string.IsNullOrWhiteSpace(raw) ? resp.ReasonPhrase ?? "Evaluator error" : raw));
            }
            catch (Exception ex)
            {
                _logger.LogWarning(ex, "KnowledgeBase forward failed for {Method} {Url}", method, relativeUrl);
                return (503, ApiResponse<JsonElement>.FailureResponse($"Không thể kết nối AI Evaluator RAG service: {ex.Message}"));
            }
        }

        private static (int StatusCode, ApiResponse<JsonElement> Body) BadRequest(string message)
            => (400, ApiResponse<JsonElement>.FailureResponse(message));
    }
}

