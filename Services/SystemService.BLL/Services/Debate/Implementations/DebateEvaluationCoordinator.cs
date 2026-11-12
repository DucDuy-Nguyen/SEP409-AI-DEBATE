using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;
using SystemService.BLL.DTOs.Debate;
using SystemService.BLL.Services.Debate.Interfaces;

namespace SystemService.BLL.Services.Debate.Implementations
{
    /// <summary>
    /// Singleton: at most ONE evaluation runs per debate session in this process. A request that arrives while the
    /// session is being evaluated (auto-evaluation of the last turn, GET /evaluation, POST /evaluate) awaits the same
    /// task instead of starting a second evaluation. Only covers one SystemService instance (no distributed lock).
    /// </summary>
    public sealed class DebateEvaluationCoordinator
    {
        private readonly ConcurrentDictionary<int, Lazy<Task<DebateEvaluationResponse>>> _inFlight = new();
        private readonly IServiceScopeFactory? _scopeFactory;

        /// <param name="scopeFactory">
        /// The API passes it: each evaluation then runs on a DebateService (and DbContext) of its OWN scope, so it is
        /// not tied to the request that started it, which may end (client gone) while others still wait for the result.
        /// Without it (unit tests) the evaluation runs on the starting caller's service.
        /// </param>
        public DebateEvaluationCoordinator(IServiceScopeFactory? scopeFactory = null, ILogger<DebateEvaluationCoordinator>? logger = null)
        {
            _scopeFactory = scopeFactory;
            // The lock lives in this process only: two replicas could each evaluate the same debate (2 AIJudgements)
            logger?.LogInformation(
                "DebateEvaluationCoordinator is in-memory: run SystemService as a single replica, or move the per-session lock to the database before scaling out.");
        }

        /// <summary>
        /// Starts (or joins) the evaluation of a debate without waiting for it: used when the last turn is submitted,
        /// so the response returns at once. A failure is only logged: the next GET /evaluation evaluates again.
        /// </summary>
        public void StartInBackground(
            int sessionId,
            DebateService caller,
            Func<DebateService, Task<DebateEvaluationResponse>> evaluate,
            ILogger? logger)
        {
            if (_scopeFactory == null)
            {
                // Only outside the API (no DI): the evaluation then shares the caller's DbContext, which goes on in parallel
                logger?.LogWarning("Background evaluation of debate session {SessionId} without a scope factory.", sessionId);
            }
            RunOnceAsync(sessionId, caller, evaluate).ContinueWith(
                t => logger?.LogWarning(t.Exception?.GetBaseException(),
                    "Background evaluation of debate session {SessionId} failed; the next GET /evaluation will evaluate it again.", sessionId),
                CancellationToken.None,
                TaskContinuationOptions.OnlyOnFaulted | TaskContinuationOptions.ExecuteSynchronously,
                TaskScheduler.Default);
        }

        /// <summary>
        /// Runs <paramref name="evaluate"/> unless an evaluation of the session is already running, in which case the
        /// running one is awaited. <paramref name="cancellationToken"/> only stops THIS caller from waiting: the shared
        /// evaluation keeps running and is stored for the others.
        /// </summary>
        public Task<DebateEvaluationResponse> RunOnceAsync(
            int sessionId,
            DebateService caller,
            Func<DebateService, Task<DebateEvaluationResponse>> evaluate,
            CancellationToken cancellationToken = default)
        {
            // Only the Lazy that ends up in the dictionary is ever started (a losing candidate is dropped unstarted)
            Lazy<Task<DebateEvaluationResponse>>? candidate = null;
            candidate = new Lazy<Task<DebateEvaluationResponse>>(() => Task.Run(async () =>
            {
                try
                {
                    return await RunInOwnScopeAsync(caller, evaluate);
                }
                finally
                {
                    // Freed BEFORE the task completes: whoever sees it finished (or failed) and asks again gets a new
                    // evaluation (a failure is retried), never the old faulted task
                    _inFlight.TryRemove(new KeyValuePair<int, Lazy<Task<DebateEvaluationResponse>>>(sessionId, candidate!));
                }
            }), LazyThreadSafetyMode.ExecutionAndPublication);
            var entry = _inFlight.GetOrAdd(sessionId, candidate);
            return entry.Value.WaitAsync(cancellationToken);
        }

        public bool IsRunning(int sessionId) => _inFlight.ContainsKey(sessionId);

        /// <summary>True while any evaluation runs (tests wait for it before disposing their database).</summary>
        public bool HasRunningEvaluations => !_inFlight.IsEmpty;

        private async Task<DebateEvaluationResponse> RunInOwnScopeAsync(
            DebateService caller, Func<DebateService, Task<DebateEvaluationResponse>> evaluate)
        {
            if (_scopeFactory == null)
            {
                return await evaluate(caller);
            }
            await using var scope = _scopeFactory.CreateAsyncScope();
            var service = (DebateService)scope.ServiceProvider.GetRequiredService<IDebateService>();
            return await evaluate(service);
        }
    }
}
