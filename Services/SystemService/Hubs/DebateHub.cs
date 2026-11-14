using System;
using System.Security.Claims;
using System.Threading.Tasks;
using Microsoft.AspNetCore.SignalR;
using Microsoft.Extensions.Logging;

namespace SystemService.Hubs
{
    public class DebateHub : Hub
    {
        private readonly ILogger<DebateHub> _logger;

        public DebateHub(ILogger<DebateHub> logger)
        {
            _logger = logger;
        }

        public async Task JoinRoom(int sessionId)
        {
            var groupName = GetGroupName(sessionId);
            await Groups.AddToGroupAsync(Context.ConnectionId, groupName);

            var userId = GetUserId();
            var fullName = GetUserFullName();

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

        public override async Task OnDisconnectedAsync(Exception? exception)
        {
            var userId = GetUserId();
            var fullName = GetUserFullName();
            _logger.LogInformation("Connection {ConnectionId} for User {UserId} disconnected.", Context.ConnectionId, userId);
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

