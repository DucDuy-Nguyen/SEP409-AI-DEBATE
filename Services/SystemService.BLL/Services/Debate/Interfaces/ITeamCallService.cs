using System.Threading;
using System.Threading.Tasks;
using SystemService.BLL.Common.Responses;
using SystemService.BLL.DTOs.Debate;

namespace SystemService.BLL.Services.Debate.Interfaces
{
    /// <summary>Team call of a 2v2 side during the preparation minute (see DebateTeamCall).</summary>
    public interface ITeamCallService
    {
        /// <summary>
        /// May <paramref name="userId"/> send a signal of <paramref name="signalType"/> now, and to whom. A hangup is
        /// always allowed to a teammate (a call is torn down after the minute too); the others only while preparing.
        /// </summary>
        Task<ApiResponse<TeamCallPeers>> AuthorizeSignalAsync(int userId, int sessionId, string signalType, CancellationToken cancellationToken = default);

        /// <summary>STUN / TURN servers for a human debater who has a teammate, while the session is not over.</summary>
        Task<ApiResponse<IceServersResponse>> GetIceServersAsync(int userId, int sessionId, CancellationToken cancellationToken = default);
    }

    /// <summary>Where the ICE servers come from (TURN credentials must be generated server-side).</summary>
    public interface IIceServerProvider
    {
        Task<IceServersResponse> GetIceServersAsync(CancellationToken cancellationToken = default);
    }
}
