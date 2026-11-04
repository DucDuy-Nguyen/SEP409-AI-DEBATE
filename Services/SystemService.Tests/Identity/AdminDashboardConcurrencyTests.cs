using System.Reflection;
using SystemService.BLL.Services.Identity.Implementations;
using SystemService.DAL.Repositories.Debate.Interfaces;
using SystemService.DAL.Repositories.Identity.Interfaces;
using SystemService.Tests.Debate;

namespace SystemService.Tests.Identity
{
    public class AdminDashboardConcurrencyTests
    {
        // The repositories share one scoped DbContext, which rejects overlapping queries: on SQL Server the parallel
        // version failed every call with "A second operation was started". EF InMemory cannot reproduce that, so
        // this detects the overlap itself.
        [Fact]
        public async Task Queries_NeverOverlap_BecauseRepositoriesShareOneDbContext()
        {
            var tracker = new OverlapTracker();
            var service = new AdminService(
                OverlapDetectingRepository<IUserRepository>.Create(tracker),
                null!,
                OverlapDetectingRepository<IDebateRepository>.Create(tracker),
                OverlapDetectingRepository<ITopicRepository>.Create(tracker));

            var stats = ApiResponseAssert.Succeeds(await service.GetDashboardStatsAsync());

            Assert.Equal(0, tracker.Overlaps);
            Assert.Equal(3, tracker.Calls);
            Assert.Equal(7, stats.TotalDebateSessions);
        }

        private sealed class OverlapTracker
        {
            private int _active;
            private int _overlaps;
            private int _calls;

            public int Overlaps => _overlaps;
            public int Calls => _calls;

            public async Task<int> CountAsync()
            {
                Interlocked.Increment(ref _calls);
                if (Interlocked.Increment(ref _active) > 1)
                {
                    Interlocked.Increment(ref _overlaps);
                }
                await Task.Delay(20);
                Interlocked.Decrement(ref _active);
                return 7;
            }
        }

        public class OverlapDetectingRepository<T> : DispatchProxy where T : class
        {
            private object _tracker = null!;

            internal static T Create(object tracker)
            {
                var proxy = Create<T, OverlapDetectingRepository<T>>();
                ((OverlapDetectingRepository<T>)(object)proxy)._tracker = tracker;
                return proxy;
            }

            protected override object? Invoke(MethodInfo? targetMethod, object?[]? args)
            {
                return ((OverlapTracker)_tracker).CountAsync();
            }
        }
    }
}
