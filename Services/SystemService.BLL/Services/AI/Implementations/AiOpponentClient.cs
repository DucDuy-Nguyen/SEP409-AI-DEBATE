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
    public class AiOpponentClient : IAiOpponentClient
    {
        private readonly HttpClient _httpClient;
        private readonly ILogger<AiOpponentClient> _logger;

        public AiOpponentClient(HttpClient httpClient, ILogger<AiOpponentClient> logger)
        {
            _httpClient = httpClient;
            _logger = logger;
        }

        public async Task<CreateOpponentSessionResponse?> InitCasePlanAsync(CreateOpponentSessionRequest req, CancellationToken ct = default)
        {
            try
            {
                var response = await _httpClient.PostAsJsonAsync("/opponent/sessions", req, ct);
                response.EnsureSuccessStatusCode();
                return await response.Content.ReadFromJsonAsync<CreateOpponentSessionResponse>(cancellationToken: ct);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Failed to call AI Opponent InitCasePlanAsync for external_session_id {SessionId}", req.ExternalSessionId);
                throw;
            }
        }

        public async Task<GenerateTurnResponse?> GenerateCounterSpeechAsync(string externalSessionId, GenerateTurnRequest req, CancellationToken ct = default)
        {
            try
            {
                var response = await _httpClient.PostAsJsonAsync($"/opponent/sessions/{externalSessionId}/turns", req, ct);
                response.EnsureSuccessStatusCode();
                return await response.Content.ReadFromJsonAsync<GenerateTurnResponse>(cancellationToken: ct);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Failed to call AI Opponent GenerateCounterSpeechAsync for session {SessionId}, turn {TurnIndex}", externalSessionId, req.TurnIndex);
                throw;
            }
        }
    }
}
