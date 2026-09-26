using Microsoft.Extensions.Caching.Distributed;
using System;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using SystemService.BLL.Models.Identity;
using SystemService.BLL.Services.Identity.Interfaces;

namespace SystemService.BLL.Services.Identity.Implementations
{
    public class OtpCacheService : IOtpCacheService
    {
        private readonly IDistributedCache _cache;
        private static readonly JsonSerializerOptions SerializerOptions = new()
        {
            PropertyNameCaseInsensitive = true
        };

        public OtpCacheService(IDistributedCache cache)
        {
            _cache = cache;
        }

        private static string BuildKey(string email, string type)
        {
            var normalizedEmail = email.Trim().ToLowerInvariant();
            var normalizedType = type.Trim().ToLowerInvariant();
            return $"otp:{normalizedType}:{normalizedEmail}";
        }

        public async Task SaveOtpAsync(string email, string code, string type, TimeSpan expiry, CancellationToken cancellationToken = default)
        {
            var key = BuildKey(email, type);
            var item = new OtpCacheItem
            {
                Email = email.Trim().ToLowerInvariant(),
                Code = code.Trim(),
                Type = type.Trim(),
                CreatedAt = DateTime.UtcNow
            };

            var json = JsonSerializer.Serialize(item, SerializerOptions);
            var options = new DistributedCacheEntryOptions
            {
                AbsoluteExpirationRelativeToNow = expiry
            };

            await _cache.SetStringAsync(key, json, options, cancellationToken);
        }

        public async Task<OtpCacheItem?> GetOtpAsync(string email, string type, CancellationToken cancellationToken = default)
        {
            var key = BuildKey(email, type);
            var json = await _cache.GetStringAsync(key, cancellationToken);

            if (string.IsNullOrEmpty(json))
            {
                return null;
            }

            try
            {
                return JsonSerializer.Deserialize<OtpCacheItem>(json, SerializerOptions);
            }
            catch
            {
                return null;
            }
        }

        public async Task RemoveOtpAsync(string email, string type, CancellationToken cancellationToken = default)
        {
            var key = BuildKey(email, type);
            await _cache.RemoveAsync(key, cancellationToken);
        }
    }
}
