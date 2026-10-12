using System;
using System.Net.Http;
using System.Net.Http.Json;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.Logging;
using SystemService.BLL.DTOs.AI;
using SystemService.BLL.Services.AI.Interfaces;

namespace SystemService.BLL.Services.AI.Implementations
{
    public class AiEvaluatorClient : IAiEvaluatorClient
    {
        private readonly HttpClient _httpClient;
        private readonly ILogger<AiEvaluatorClient> _logger;

        public AiEvaluatorClient(HttpClient httpClient, ILogger<AiEvaluatorClient> logger)
        {
            _httpClient = httpClient;
            _logger = logger;
        }

        public async Task<EvaluateArgumentResponse?> EvaluateArgumentAsync(EvaluateArgumentRequest req, CancellationToken ct = default)
        {
            try
            {
                var response = await _httpClient.PostAsJsonAsync("/evaluate", req, ct);
                response.EnsureSuccessStatusCode();
                return await response.Content.ReadFromJsonAsync<EvaluateArgumentResponse>(cancellationToken: ct);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Failed to call AI Evaluator EvaluateArgumentAsync for motion {Motion}", req.Motion);
                throw;
            }
        }

        public async Task<EvaluateRoundResponse?> EvaluateRoundAsync(EvaluateRoundRequest req, CancellationToken ct = default)
        {
            try
            {
                var response = await _httpClient.PostAsJsonAsync("/evaluate/round", req, ct);
                response.EnsureSuccessStatusCode();
                return await response.Content.ReadFromJsonAsync<EvaluateRoundResponse>(cancellationToken: ct);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Failed to call AI Evaluator EvaluateRoundAsync for stage {Stage}", req.Stage);
                throw;
            }
        }

        public async Task<EvaluateSessionResponse?> EvaluateSessionAsync(EvaluateSessionRequest req, CancellationToken ct = default)
        {
            try
            {
                var response = await _httpClient.PostAsJsonAsync("/evaluate/session", req, ct);
                response.EnsureSuccessStatusCode();
                return await response.Content.ReadFromJsonAsync<EvaluateSessionResponse>(cancellationToken: ct);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Failed to call AI Evaluator EvaluateSessionAsync");
                throw;
            }
        }
    }
}
