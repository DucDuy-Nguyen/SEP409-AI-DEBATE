using System;
using System.Threading;
using System.Threading.Tasks;
using SystemService.BLL.Common.Debate;
using SystemService.BLL.Common.Responses;
using SystemService.BLL.DTOs.Debate;
using SystemService.BLL.Services.Debate.Interfaces;
using SystemService.DAL.Entities.Debate;
using SystemService.DAL.Entities.Debate.Enums;
using SystemService.DAL.Repositories.Debate.Interfaces;

namespace SystemService.BLL.Services.Debate.Implementations
{
    public class TeamCallService : ITeamCallService
    {
        private readonly IDebateRepository _debateRepository;
        private readonly IIceServerProvider _iceServerProvider;

        public TeamCallService(IDebateRepository debateRepository, IIceServerProvider iceServerProvider)
        {
            _debateRepository = debateRepository;
            _iceServerProvider = iceServerProvider;
        }

        public async Task<ApiResponse<TeamCallPeers>> AuthorizeSignalAsync(
            int userId, int sessionId, string signalType, CancellationToken cancellationToken = default)
        {
            if (!DebateTeamCall.IsSignalType(signalType))
            {
                return Failure<TeamCallPeers>("Loại tín hiệu cuộc gọi không hợp lệ.", DebateErrorCodes.InvalidRequest);
            }

            var session = await _debateRepository.GetSessionWithDetailsAsync(sessionId, cancellationToken);
            var (peers, failure) = TeammatesOf(session, userId);
            if (failure != null)
            {
                return Failure<TeamCallPeers>(failure.Value.Message, failure.Value.Code);
            }

            if (signalType != DebateTeamCall.Hangup)
            {
                if (session!.Status != SessionStatus.InProgress)
                {
                    return Failure<TeamCallPeers>("Phiên tranh biện không đang diễn ra.", DebateErrorCodes.SessionNotInProgress);
                }
                if (!DebatePreparation.IsPreparing(session, DateTime.UtcNow))
                {
                    return Failure<TeamCallPeers>("Chỉ được gọi đồng đội trong thời gian chuẩn bị.", DebateErrorCodes.TeamCallClosed);
                }
            }

            return ApiResponse<TeamCallPeers>.SuccessResponse(peers!, "OK");
        }

        public async Task<ApiResponse<IceServersResponse>> GetIceServersAsync(
            int userId, int sessionId, CancellationToken cancellationToken = default)
        {
            var session = await _debateRepository.GetSessionWithDetailsAsync(sessionId, cancellationToken);
            var (_, failure) = TeammatesOf(session, userId);
            if (failure != null)
            {
                return Failure<IceServersResponse>(failure.Value.Message, failure.Value.Code);
            }

            // Fetched ahead (in the lobby or before a round): only a finished session has no call left
            if (session!.Status is SessionStatus.Completed or SessionStatus.Cancelled)
            {
                return Failure<IceServersResponse>("Phiên tranh biện đã kết thúc.", DebateErrorCodes.SessionNotInProgress);
            }

            var servers = await _iceServerProvider.GetIceServersAsync(cancellationToken);
            return ApiResponse<IceServersResponse>.SuccessResponse(servers, "OK");
        }

        private static (TeamCallPeers? Peers, (string Message, string Code)? Failure) TeammatesOf(DebateSession? session, int userId)
        {
            if (session == null)
            {
                return (null, ("Không tìm thấy phiên tranh biện.", DebateErrorCodes.SessionNotFound));
            }
            if (DebateTeamCall.HumanParticipant(session, userId) == null)
            {
                return (null, ("Bạn không phải người tranh biện trong phiên này.", DebateErrorCodes.NotParticipant));
            }
            var teammates = DebateTeamCall.TeammateUserIds(session, userId);
            if (teammates.Count == 0)
            {
                return (null, ("Bạn không có đồng đội để gọi trong phiên này.", DebateErrorCodes.NoTeammate));
            }
            return (new TeamCallPeers { SessionId = session.DebateSessionId, TeammateUserIds = teammates }, null);
        }

        private static ApiResponse<T> Failure<T>(string message, string code) =>
            ApiResponse<T>.FailureResponse(message, new ApiErrorDetail(code));
    }
}
