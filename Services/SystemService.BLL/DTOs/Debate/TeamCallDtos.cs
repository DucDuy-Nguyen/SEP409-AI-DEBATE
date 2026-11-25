using System.Collections.Generic;

namespace SystemService.BLL.DTOs.Debate
{
    /// <summary>Who receives a team call signal: the caller's human teammate(s).</summary>
    public class TeamCallPeers
    {
        public int SessionId { get; set; }
        public List<int> TeammateUserIds { get; set; } = new();
    }

    /// <summary>One entry of RTCPeerConnection's iceServers.</summary>
    public class IceServerDto
    {
        public List<string> Urls { get; set; } = new();
        public string? Username { get; set; }
        public string? Credential { get; set; }
    }

    /// <summary>GET /api/debate/{id}/ice-servers: STUN, plus TURN with short-lived credentials when configured.</summary>
    public class IceServersResponse
    {
        public List<IceServerDto> IceServers { get; set; } = new();
        // How long the TURN credentials stay valid (0 when there is no TURN)
        public int TtlSeconds { get; set; }
    }
}
