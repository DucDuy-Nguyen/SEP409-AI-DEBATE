using System;
using System.Collections.Concurrent;
using System.Linq;
using System.Security.Claims;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.AspNetCore.SignalR;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Logging;
using SystemService.BLL.Services.Debate.Interfaces;

namespace SystemService.Hubs
{
    public class DebateHub : Hub
    {
        private static readonly TimeSpan DisconnectGracePeriod = TimeSpan.FromSeconds(15);

        private static readonly ConcurrentDictionary<string, (int SessionId, int? UserId, string FullName)> _connectionRooms = new();
        private static readonly ConcurrentDictionary<(int SessionId, int UserId), CancellationTokenSource> _pendingDisconnects = new();

        private readonly ILogger<DebateHub> _logger;
        private readonly IServiceScopeFactory _scopeFactory;

        public DebateHub(ILogger<DebateHub> logger, IServiceScopeFactory scopeFactory)
        {
            _logger = logger;
            _scopeFactory = scopeFactory;
        }

        public async Task JoinRoom(int sessionId)
        {
            var groupName = GetGroupName(sessionId);
            await Groups.AddToGroupAsync(Context.ConnectionId, groupName);

            var userId = GetUserId();
            var fullName = GetUserFullName();

            _connectionRooms[Context.ConnectionId] = (sessionId, userId, fullName);

            // Cancel any pending disconnect grace-period timer if the user reconnected (e.g. page refresh)
            if (userId.HasValue && _pendingDisconnects.TryRemove((sessionId, userId.Value), out var pendingCts))
            {
                pendingCts.Cancel();
                pendingCts.Dispose();
            }

            _logger.LogInformation("User {UserId} ({FullName}) connected to debate room {SessionId}", userId, fullName, sessionId);

            // Broadcast to other users in this room that a debater has entered
            await Clients.OthersInGroup(groupName).SendAsync("UserJoinedRoom", new
            {
                SessionId = sessionId,
                UserId = userId,
                FullName = fullName,
                ConnectionId = Context.ConnectionId,
                JoinedAt = DateTime.UtcNow
            });
        }

        public async Task LeaveRoom(int sessionId)
        {
            var groupName = GetGroupName(sessionId);
            await Groups.RemoveFromGroupAsync(Context.ConnectionId, groupName);
            _connectionRooms.TryRemove(Context.ConnectionId, out _);

            var userId = GetUserId();
            var fullName = GetUserFullName();

            _logger.LogInformation("User {UserId} ({FullName}) left debate room {SessionId}", userId, fullName, sessionId);

            await Clients.OthersInGroup(groupName).SendAsync("UserLeftRoom", new
            {
                SessionId = sessionId,
                UserId = userId,
                FullName = fullName,
                Timestamp = DateTime.UtcNow
            });
        }

        public async Task SendSpeakingStatus(int sessionId, bool isSpeaking)
        {
            var groupName = GetGroupName(sessionId);
            var userId = GetUserId();
            var fullName = GetUserFullName();

            // Broadcast speaking indicator so opponents / judges see live waveforms or speaking badges
            await Clients.OthersInGroup(groupName).SendAsync("UserSpeakingStatusChanged", new
            {
                SessionId = sessionId,
                UserId = userId,
                FullName = fullName,
                IsSpeaking = isSpeaking
            });
        }

        public async Task SendLiveTranscript(int sessionId, string text, bool isFinal, bool speechFinal = false, int sequence = 0)
        {
            if (string.IsNullOrWhiteSpace(text) && !isFinal)
            {
                return;
            }

            var groupName = GetGroupName(sessionId);
            var userId = GetUserId();
            var fullName = GetUserFullName();

            await Clients.OthersInGroup(groupName).SendAsync("LiveTranscriptUpdated", new
            {
                SessionId = sessionId,
                UserId = userId,
                FullName = fullName,
                Text = text,
                IsFinal = isFinal,
                SpeechFinal = speechFinal,
                Sequence = sequence,
                Timestamp = DateTime.UtcNow
            });
        }

        public override async Task OnDisconnectedAsync(Exception? exception)
        {
            var userId = GetUserId();
            _logger.LogInformation("Connection {ConnectionId} for User {UserId} disconnected.", Context.ConnectionId, userId);

            if (_connectionRooms.TryRemove(Context.ConnectionId, out var roomInfo))
            {
                var groupName = GetGroupName(roomInfo.SessionId);
                await Clients.OthersInGroup(groupName).SendAsync("UserLeftRoom", new
                {
                    SessionId = roomInfo.SessionId,
                    UserId = roomInfo.UserId,
                    FullName = roomInfo.FullName,
                    Timestamp = DateTime.UtcNow
                });

                if (roomInfo.UserId.HasValue)
                {
                    int sessionId = roomInfo.SessionId;
                    int disconnectedUserId = roomInfo.UserId.Value;

                    // Do not cancel if the same user still has another active tab/connection in this room
                    bool stillConnected = _connectionRooms.Values.Any(
                        v => v.SessionId == sessionId && v.UserId == disconnectedUserId);

                    if (!stillConnected)
                    {
                        var key = (sessionId, disconnectedUserId);
                        var cts = new CancellationTokenSource();
                        if (_pendingDisconnects.TryRemove(key, out var previousCts))
                        {
                            previousCts.Cancel();
                            previousCts.Dispose();
                        }
                        _pendingDisconnects[key] = cts;

                        _ = Task.Run(async () =>
                        {
                            try
                            {
                                await Task.Delay(DisconnectGracePeriod, cts.Token);

                                if (_connectionRooms.Values.Any(
                                    v => v.SessionId == sessionId && v.UserId == disconnectedUserId))
                                {
                                    return;
                                }

                                using var scope = _scopeFactory.CreateScope();
                                var debateService = scope.ServiceProvider.GetRequiredService<IDebateService>();
                                var result = await debateService.LeaveSessionAsync(disconnectedUserId, sessionId, CancellationToken.None);
                                _logger.LogInformation(
                                    "Auto-cancelled debate session {SessionId} after User {UserId} remained disconnected for {Seconds}s (Success={Success}).",
                                    sessionId, disconnectedUserId, DisconnectGracePeriod.TotalSeconds, result.Success);
                            }
                            catch (TaskCanceledException)
                            {
                                // User reconnected within grace period
                            }
                            catch (Exception ex)
                            {
                                _logger.LogWarning(
                                    ex,
                                    "Error auto-leaving debate session {SessionId} for disconnected User {UserId}.",
                                    sessionId, disconnectedUserId);
                            }
                            finally
                            {
                                if (_pendingDisconnects.TryGetValue(key, out var current) && ReferenceEquals(current, cts))
                                {
                                    _pendingDisconnects.TryRemove(key, out _);
                                }
                                cts.Dispose();
                            }
                        });
                    }
                }
            }

            await base.OnDisconnectedAsync(exception);
        }

        public static string GetGroupName(int sessionId) => $"debate_{sessionId}";

        private int? GetUserId()
        {
            var claim = Context.User?.FindFirst(ClaimTypes.NameIdentifier) 
                     ?? Context.User?.FindFirst("sub") 
                     ?? Context.User?.FindFirst("userId")
                     ?? Context.User?.FindFirst("id");
            if (claim != null && int.TryParse(claim.Value, out int id))
            {
                return id;
            }
            return null;
        }

        private string GetUserFullName()
        {
            var nameClaim = Context.User?.FindFirst(ClaimTypes.Name) 
                         ?? Context.User?.FindFirst("fullName") 
                         ?? Context.User?.FindFirst("FullName");
            return nameClaim?.Value ?? "Thí sinh";
        }
    }
}

