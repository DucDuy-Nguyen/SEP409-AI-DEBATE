using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.DependencyInjection;
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
        public DebateEvaluationCoordinator(IServiceScopeFactory? scopeFactory = null)
        {
            _scopeFactory = scopeFactory;
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
            // Lazy: GetOrAdd may call the factory twice under a race, but only the stored Lazy is ever started
            var entry = _inFlight.GetOrAdd(sessionId, _ => new Lazy<Task<DebateEvaluationResponse>>(
                () => Task.Run(() => RunInOwnScopeAsync(caller, evaluate)), LazyThreadSafetyMode.ExecutionAndPublication));
            var task = entry.Value;
            // Free the slot once done (success or failure): a failed evaluation can be retried by the next request
            task.ContinueWith(
                _ => _inFlight.TryRemove(new KeyValuePair<int, Lazy<Task<DebateEvaluationResponse>>>(sessionId, entry)),
                CancellationToken.None, TaskContinuationOptions.ExecuteSynchronously, TaskScheduler.Default);
            return task.WaitAsync(cancellationToken);
        }

        public bool IsRunning(int sessionId) => _inFlight.ContainsKey(sessionId);

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
