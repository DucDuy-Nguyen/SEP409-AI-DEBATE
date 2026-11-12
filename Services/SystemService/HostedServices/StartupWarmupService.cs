using System.Diagnostics;
using SystemService.BLL.Services.Debate.Interfaces;
using SystemService.DAL.Repositories.Debate.Interfaces;

namespace SystemService.HostedServices
{
    /// <summary>
    /// Warms up what the first evaluation of a debate needs, right after startup and in the background (startup is
    /// never blocked): the EF model and the session query used by the evaluation, the DebateService graph, and the AI
    /// Evaluator (GET /health/ready, which also says whether its RAG model is loaded). Measured: the first evaluation
    /// after a cold start took 34 s against 15-27 s later. A failure is only logged as a warning.
    /// </summary>
    public sealed class StartupWarmupService : BackgroundService
    {
        public const string EvaluatorHttpClientName = "evaluator-warmup";

        private readonly IServiceScopeFactory _scopeFactory;
        private readonly IHttpClientFactory _httpClientFactory;
        private readonly ILogger<StartupWarmupService> _logger;

        public StartupWarmupService(IServiceScopeFactory scopeFactory, IHttpClientFactory httpClientFactory, ILogger<StartupWarmupService> logger)
        {
            _scopeFactory = scopeFactory;
            _httpClientFactory = httpClientFactory;
            _logger = logger;
        }

        protected override async Task ExecuteAsync(CancellationToken stoppingToken)
        {
            await Task.Yield(); // return to the host at once: startup does not wait for the warm-up
            await WarmUpDatabaseAsync(stoppingToken);
            await WarmUpEvaluatorAsync(stoppingToken);
        }

        private async Task WarmUpDatabaseAsync(CancellationToken stoppingToken)
        {
            var stopwatch = Stopwatch.StartNew();
            try
            {
                await using var scope = _scopeFactory.CreateAsyncScope();
                _ = scope.ServiceProvider.GetRequiredService<IDebateService>();
                // The same query as an evaluation (no such session): builds the EF model, compiles the query, opens the pool
                await scope.ServiceProvider.GetRequiredService<IDebateRepository>().GetSessionWithDetailsAsync(-1, stoppingToken);
                _logger.LogInformation("Warm-up: database ready in {ElapsedMs} ms", stopwatch.ElapsedMilliseconds);
            }
            catch (Exception ex) when (ex is not OperationCanceledException)
            {
                _logger.LogWarning(ex, "Warm-up: database query failed after {ElapsedMs} ms", stopwatch.ElapsedMilliseconds);
            }
        }

        private async Task WarmUpEvaluatorAsync(CancellationToken stoppingToken)
        {
            var stopwatch = Stopwatch.StartNew();
            try
            {
                var client = _httpClientFactory.CreateClient(EvaluatorHttpClientName);
                using var response = await client.GetAsync("health/ready", stoppingToken);
                if (response.IsSuccessStatusCode)
                {
                    _logger.LogInformation("Warm-up: AI Evaluator ready in {ElapsedMs} ms", stopwatch.ElapsedMilliseconds);
                }
                else
                {
                    // 503 while the evaluator still loads its RAG model: evaluations work, the evidence check may wait
                    _logger.LogWarning("Warm-up: AI Evaluator /health/ready returned {StatusCode} after {ElapsedMs} ms",
                        (int)response.StatusCode, stopwatch.ElapsedMilliseconds);
                }
            }
            catch (Exception ex) when (ex is not OperationCanceledException || !stoppingToken.IsCancellationRequested)
            {
                _logger.LogWarning(ex, "Warm-up: AI Evaluator not reachable after {ElapsedMs} ms", stopwatch.ElapsedMilliseconds);
            }
        }
    }
}
