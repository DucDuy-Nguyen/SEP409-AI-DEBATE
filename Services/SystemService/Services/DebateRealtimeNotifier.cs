using System;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.AspNetCore.SignalR;
using Microsoft.Extensions.Logging;
using SystemService.BLL.Services.Debate.Interfaces;
using SystemService.Hubs;

namespace SystemService.Services
{
    public class DebateRealtimeNotifier : IDebateRealtimeNotifier
    {
        private readonly IHubContext<DebateHub> _hubContext;
        private readonly ILogger<DebateRealtimeNotifier> _logger;

        public DebateRealtimeNotifier(IHubContext<DebateHub> hubContext, ILogger<DebateRealtimeNotifier> logger)
        {
            _hubContext = hubContext;
            _logger = logger;
        }

        public async Task NotifyUserJoinedAsync(int sessionId, int userId, string fullName, string side, CancellationToken cancellationToken = default)
        {
            try
            {
                var groupName = DebateHub.GetGroupName(sessionId);
                await _hubContext.Clients.Group(groupName).SendAsync("ParticipantJoined", new
                {
                    SessionId = sessionId,
                    UserId = userId,
                    FullName = fullName,
                    Side = side,
                    Timestamp = DateTime.UtcNow
                }, cancellationToken);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Failed to broadcast NotifyUserJoinedAsync for session {SessionId}", sessionId);
            }
        }

        public async Task NotifyUserLeftAsync(int sessionId, int userId, string fullName, CancellationToken cancellationToken = default)
        {
            try
            {
                var groupName = DebateHub.GetGroupName(sessionId);
                await _hubContext.Clients.Group(groupName).SendAsync("ParticipantLeft", new
                {
                    SessionId = sessionId,
                    UserId = userId,
                    FullName = fullName,
                    Timestamp = DateTime.UtcNow
                }, cancellationToken);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Failed to broadcast NotifyUserLeftAsync for session {SessionId}", sessionId);
            }
        }

        public async Task NotifyArgumentSubmittedAsync(int sessionId, object argumentData, object? turnData, CancellationToken cancellationToken = default)
        {
            try
            {
                var groupName = DebateHub.GetGroupName(sessionId);
                await _hubContext.Clients.Group(groupName).SendAsync("ArgumentSubmitted", new
                {
                    SessionId = sessionId,
                    Argument = argumentData,
                    Turn = turnData,
                    Timestamp = DateTime.UtcNow
                }, cancellationToken);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Failed to broadcast NotifyArgumentSubmittedAsync for session {SessionId}", sessionId);
            }
        }

        public async Task NotifySessionStartedAsync(int sessionId, object sessionData, CancellationToken cancellationToken = default)
        {
            try
            {
                var groupName = DebateHub.GetGroupName(sessionId);
                await _hubContext.Clients.Group(groupName).SendAsync("SessionStarted", new
                {
                    SessionId = sessionId,
                    Session = sessionData,
                    Timestamp = DateTime.UtcNow
                }, cancellationToken);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Failed to broadcast NotifySessionStartedAsync for session {SessionId}", sessionId);
            }
        }

        public async Task NotifySessionStatusChangedAsync(int sessionId, string status, string? reason = null, CancellationToken cancellationToken = default)
        {
            try
            {
                var groupName = DebateHub.GetGroupName(sessionId);
                await _hubContext.Clients.Group(groupName).SendAsync("SessionStatusChanged", new
                {
                    SessionId = sessionId,
                    Status = status,
                    Reason = reason,
                    Timestamp = DateTime.UtcNow
                }, cancellationToken);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Failed to broadcast NotifySessionStatusChangedAsync for session {SessionId}", sessionId);
            }
        }
    }
}

