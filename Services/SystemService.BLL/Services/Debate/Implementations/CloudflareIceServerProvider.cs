using System;
using System.Collections.Generic;
using System.Linq;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;
using SystemService.BLL.DTOs.Debate;
using SystemService.BLL.Services.Debate.Interfaces;

namespace SystemService.BLL.Services.Debate.Implementations
{
    /// <summary>
    /// ICE servers for the team call: STUN always, plus TURN from Cloudflare Realtime (free tier) when
    /// TeamCall:Cloudflare:TurnKeyId and TeamCall:Cloudflare:TurnKeyApiToken are set. The credentials are generated
    /// here, short-lived, so the API token never reaches the browser. Without them, or when Cloudflare fails, the call
    /// falls back to STUN only (most networks connect; strict NATs need TURN).
    /// https://developers.cloudflare.com/realtime/turn/generate-credentials/
    /// </summary>
    public class CloudflareIceServerProvider : IIceServerProvider
    {
        public const string DefaultStunUrl = "stun:stun.cloudflare.com:3478";
        private const int DefaultTtlSeconds = 2 * 60 * 60; // a whole debate, with margin (Cloudflare allows up to 48 h)

        private readonly HttpClient _httpClient;
        private readonly IConfiguration _configuration;
        private readonly ILogger<CloudflareIceServerProvider>? _logger;

        public CloudflareIceServerProvider(HttpClient httpClient, IConfiguration configuration, ILogger<CloudflareIceServerProvider>? logger = null)
        {
            _httpClient = httpClient;
            _configuration = configuration;
            _logger = logger;
        }

        public async Task<IceServersResponse> GetIceServersAsync(CancellationToken cancellationToken = default)
        {
            var stunUrls = _configuration.GetSection("TeamCall:StunUrls").Get<string[]>();
            var stun = new IceServerDto { Urls = stunUrls is { Length: > 0 } ? stunUrls.ToList() : new List<string> { DefaultStunUrl } };

            var keyId = _configuration["TeamCall:Cloudflare:TurnKeyId"];
            var apiToken = _configuration["TeamCall:Cloudflare:TurnKeyApiToken"];
            if (string.IsNullOrWhiteSpace(keyId) || string.IsNullOrWhiteSpace(apiToken))
            {
                return new IceServersResponse { IceServers = new List<IceServerDto> { stun }, TtlSeconds = 0 };
            }

            int ttl = _configuration.GetValue("TeamCall:Cloudflare:TtlSeconds", DefaultTtlSeconds);
            try
            {
                using var request = new HttpRequestMessage(HttpMethod.Post,
                    $"https://rtc.live.cloudflare.com/v1/turn/keys/{Uri.EscapeDataString(keyId)}/credentials/generate-ice-servers")
                {
                    Content = JsonContent.Create(new { ttl })
                };
                request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", apiToken);
                using var response = await _httpClient.SendAsync(request, cancellationToken);
                response.EnsureSuccessStatusCode();
                using var json = await JsonDocument.ParseAsync(await response.Content.ReadAsStreamAsync(cancellationToken), cancellationToken: cancellationToken);
                var servers = ParseIceServers(json.RootElement);
                if (servers.Count == 0)
                {
                    throw new InvalidOperationException("Cloudflare returned no ICE servers.");
                }
                return new IceServersResponse { IceServers = servers, TtlSeconds = ttl };
            }
            catch (Exception ex) when (ex is not OperationCanceledException || !cancellationToken.IsCancellationRequested)
            {
                _logger?.LogWarning(ex, "Could not get TURN credentials from Cloudflare; the team call uses STUN only.");
                return new IceServersResponse { IceServers = new List<IceServerDto> { stun }, TtlSeconds = 0 };
            }
        }

        /// <summary>
        /// {"iceServers": [ {urls, username?, credential?}, ... ]} (or a single object). URLs on port 53 are dropped:
        /// browsers block that port and the attempt only times out.
        /// </summary>
        public static List<IceServerDto> ParseIceServers(JsonElement root)
        {
            var result = new List<IceServerDto>();
            if (!root.TryGetProperty("iceServers", out var ice))
            {
                return result;
            }
            var entries = ice.ValueKind == JsonValueKind.Array ? ice.EnumerateArray().ToList() : new List<JsonElement> { ice };
            foreach (var entry in entries)
            {
                if (entry.ValueKind != JsonValueKind.Object || !entry.TryGetProperty("urls", out var urlsElement))
                {
                    continue;
                }
                var urls = (urlsElement.ValueKind == JsonValueKind.Array
                        ? urlsElement.EnumerateArray().Select(u => u.GetString())
                        : new[] { urlsElement.GetString() })
                    .Where(u => !string.IsNullOrWhiteSpace(u) && !UsesPort53(u!))
                    .Select(u => u!)
                    .ToList();
                if (urls.Count == 0)
                {
                    continue;
                }
                result.Add(new IceServerDto
                {
                    Urls = urls,
                    Username = entry.TryGetProperty("username", out var user) ? user.GetString() : null,
                    Credential = entry.TryGetProperty("credential", out var cred) ? cred.GetString() : null
                });
            }
            return result;
        }

        private static bool UsesPort53(string url)
        {
            var hostPort = url.Split('?')[0];
            return hostPort.EndsWith(":53", StringComparison.Ordinal);
        }
    }
}
