using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using SystemService.BLL.Common.Responses;
using SystemService.BLL.DTOs.Competition.Team;
using SystemService.BLL.Services.Competition.Interfaces;
using SystemService.DAL.Entities.Competition;
using SystemService.DAL.Repositories.Competition.Interfaces;
using SystemService.DAL.Repositories.Identity.Interfaces;

namespace SystemService.BLL.Services.Competition.Implementations
{
    public class CompetitionTeamRequestService : ICompetitionTeamRequestService
    {
        private readonly ICompetitionTeamRequestRepository _requestRepository;
        private readonly ICompetitionTeamRepository _teamRepository;
        private readonly ICompetitionRepository _competitionRepository;
        private readonly IUserRepository _userRepository;

        public CompetitionTeamRequestService(
            ICompetitionTeamRequestRepository requestRepository,
            ICompetitionTeamRepository teamRepository,
            ICompetitionRepository competitionRepository,
            IUserRepository userRepository)
        {
            _requestRepository = requestRepository;
            _teamRepository = teamRepository;
            _competitionRepository = competitionRepository;
            _userRepository = userRepository;
        }

        public async Task<ApiResponse<CompetitionTeamRequestResponse>> SendInvitationAsync(int competitionId, int teamId, int captainUserId, SendTeamInvitationRequest request, CancellationToken cancellationToken = default)
        {
            var competition = await _competitionRepository.GetByIdAsync(competitionId, cancellationToken);
            if (competition == null)
            {
                return ApiResponse<CompetitionTeamRequestResponse>.FailureResponse("Competition not found.");
            }

            if (competition.CompetitionType != "TEAM")
            {
                return ApiResponse<CompetitionTeamRequestResponse>.FailureResponse("Team invitations are only allowed for TEAM competitions.");
            }

            if (competition.Status != "OpenRegistration")
            {
                return ApiResponse<CompetitionTeamRequestResponse>.FailureResponse("Competition registration is not open.");
            }

            var team = await _teamRepository.GetByIdAsync(teamId, cancellationToken);
            if (team == null || team.CompetitionId != competitionId)
            {
                return ApiResponse<CompetitionTeamRequestResponse>.FailureResponse("Team not found for the specified competition.");
            }

            if (team.Status != "Active")
            {
                return ApiResponse<CompetitionTeamRequestResponse>.FailureResponse("Cannot send invitations for a non-active team.");
            }

            if (team.CaptainUserId != captainUserId)
            {
                return ApiResponse<CompetitionTeamRequestResponse>.FailureResponse("Only the team captain can send invitations.");
            }

            var targetUser = await _userRepository.GetByIdAsync(request.UserId, cancellationToken);
            if (targetUser == null)
            {
                return ApiResponse<CompetitionTeamRequestResponse>.FailureResponse("User to invite not found.");
            }

            if (request.UserId == captainUserId)
            {
                return ApiResponse<CompetitionTeamRequestResponse>.FailureResponse("Captain cannot invite themselves.");
            }

            bool alreadyInAnyTeam = await _teamRepository.IsUserCaptainOrMemberInCompetitionAsync(competitionId, request.UserId, cancellationToken);
            if (alreadyInAnyTeam)
            {
                return ApiResponse<CompetitionTeamRequestResponse>.FailureResponse("User is already a captain or member of an active team in this competition.");
            }

            int memberCount = await _teamRepository.GetTeamMemberCountAsync(teamId, cancellationToken);
            if (memberCount >= 1)
            {
                return ApiResponse<CompetitionTeamRequestResponse>.FailureResponse("Team roster is full (maximum 1 ordinary member per team).");
            }

            bool hasPending = await _requestRepository.HasPendingRequestAsync(teamId, request.UserId, cancellationToken);
            if (hasPending)
            {
                return ApiResponse<CompetitionTeamRequestResponse>.FailureResponse("There is already a pending request or invitation for this user and team.");
            }

            var teamRequest = new CompetitionTeamRequest
            {
                TeamId = teamId,
                UserId = request.UserId,
                CreatedByUserId = captainUserId,
                RequestType = "Invitation",
                Status = "Pending",
                CreatedAt = DateTime.UtcNow
            };

            await _requestRepository.AddRequestAsync(teamRequest, cancellationToken);

            var loaded = await _requestRepository.GetByIdAsync(teamRequest.RequestId, cancellationToken);
            return ApiResponse<CompetitionTeamRequestResponse>.SuccessResponse(MapToResponse(loaded ?? teamRequest), "Invitation sent successfully.");
        }

        public async Task<ApiResponse<List<CompetitionTeamRequestResponse>>> GetMyInvitationsAsync(int competitionId, int currentUserId, CancellationToken cancellationToken = default)
        {
            var list = await _requestRepository.GetMyPendingInvitationsAsync(competitionId, currentUserId, cancellationToken);
            var result = list.Select(MapToResponse).ToList();
            return ApiResponse<List<CompetitionTeamRequestResponse>>.SuccessResponse(result);
        }

        public async Task<ApiResponse<object>> AcceptInvitationAsync(int competitionId, long requestId, int currentUserId, CancellationToken cancellationToken = default)
        {
            var request = await _requestRepository.GetByIdAsync(requestId, cancellationToken);
            if (request == null || request.RequestType != "Invitation")
            {
                return ApiResponse<object>.FailureResponse("Invitation request not found.");
            }

            if (request.UserId != currentUserId)
            {
                return ApiResponse<object>.FailureResponse("You can only respond to your own invitations.");
            }

            if (request.Status != "Pending")
            {
                return ApiResponse<object>.FailureResponse("Only Pending invitations can be accepted.");
            }

            var team = await _teamRepository.GetByIdAsync(request.TeamId, cancellationToken);
            if (team == null || team.CompetitionId != competitionId)
            {
                return ApiResponse<object>.FailureResponse("Team not found for the specified competition.");
            }

            if (team.Status != "Active")
            {
                return ApiResponse<object>.FailureResponse("Cannot join a non-active team.");
            }

            bool alreadyInAnyTeam = await _teamRepository.IsUserCaptainOrMemberInCompetitionAsync(competitionId, currentUserId, cancellationToken);
            if (alreadyInAnyTeam)
            {
                return ApiResponse<object>.FailureResponse("You are already a captain or member of an active team in this competition.");
            }

            int memberCount = await _teamRepository.GetTeamMemberCountAsync(request.TeamId, cancellationToken);
            if (memberCount >= 1)
            {
                return ApiResponse<object>.FailureResponse("Team roster is full (maximum 1 ordinary member per team).");
            }

            var member = new CompetitionTeamMember
            {
                TeamId = request.TeamId,
                UserId = currentUserId,
                JoinedAt = DateTime.UtcNow
            };

            await _requestRepository.AcceptInvitationWithMemberAsync(request, member, competitionId, currentUserId, cancellationToken);
            return ApiResponse<object>.SuccessResponse(new { }, "Invitation accepted and team member joined successfully.");
        }

        public async Task<ApiResponse<object>> RejectInvitationAsync(int competitionId, long requestId, int currentUserId, RejectTeamRequestDto requestDto, CancellationToken cancellationToken = default)
        {
            var request = await _requestRepository.GetByIdAsync(requestId, cancellationToken);
            if (request == null || request.RequestType != "Invitation")
            {
                return ApiResponse<object>.FailureResponse("Invitation request not found.");
            }

            if (request.UserId != currentUserId)
            {
                return ApiResponse<object>.FailureResponse("You can only respond to your own invitations.");
            }

            if (request.Status != "Pending")
            {
                return ApiResponse<object>.FailureResponse("Only Pending invitations can be rejected.");
            }

            request.Status = "Rejected";
            request.Note = requestDto?.Reason?.Trim();
            request.RespondedAt = DateTime.UtcNow;
            request.RespondedByUserId = currentUserId;

            await _requestRepository.UpdateRequestAsync(request, cancellationToken);
            return ApiResponse<object>.SuccessResponse(new { }, "Invitation rejected successfully.");
        }

        public async Task<ApiResponse<CompetitionTeamRequestResponse>> CreateJoinRequestAsync(int competitionId, int teamId, int currentUserId, CancellationToken cancellationToken = default)
        {
            var competition = await _competitionRepository.GetByIdAsync(competitionId, cancellationToken);
            if (competition == null)
            {
                return ApiResponse<CompetitionTeamRequestResponse>.FailureResponse("Competition not found.");
            }

            if (competition.CompetitionType != "TEAM")
            {
                return ApiResponse<CompetitionTeamRequestResponse>.FailureResponse("Join requests are only allowed for TEAM competitions.");
            }

            if (competition.Status != "OpenRegistration")
            {
                return ApiResponse<CompetitionTeamRequestResponse>.FailureResponse("Competition registration is not open.");
            }

            var team = await _teamRepository.GetByIdAsync(teamId, cancellationToken);
            if (team == null || team.CompetitionId != competitionId)
            {
                return ApiResponse<CompetitionTeamRequestResponse>.FailureResponse("Team not found for the specified competition.");
            }

            if (team.Status != "Active")
            {
                return ApiResponse<CompetitionTeamRequestResponse>.FailureResponse("Cannot request to join a non-active team.");
            }

            if (team.CaptainUserId == currentUserId)
            {
                return ApiResponse<CompetitionTeamRequestResponse>.FailureResponse("Team captain cannot request to join their own team.");
            }

            bool alreadyInAnyTeam = await _teamRepository.IsUserCaptainOrMemberInCompetitionAsync(competitionId, currentUserId, cancellationToken);
            if (alreadyInAnyTeam)
            {
                return ApiResponse<CompetitionTeamRequestResponse>.FailureResponse("You are already a captain or member of an active team in this competition.");
            }

            int memberCount = await _teamRepository.GetTeamMemberCountAsync(teamId, cancellationToken);
            if (memberCount >= 1)
            {
                return ApiResponse<CompetitionTeamRequestResponse>.FailureResponse("Team roster is full (maximum 1 ordinary member per team).");
            }

            bool hasPending = await _requestRepository.HasPendingRequestAsync(teamId, currentUserId, cancellationToken);
            if (hasPending)
            {
                return ApiResponse<CompetitionTeamRequestResponse>.FailureResponse("You already have a pending request or invitation for this team.");
            }

            var teamRequest = new CompetitionTeamRequest
            {
                TeamId = teamId,
                UserId = currentUserId,
                CreatedByUserId = currentUserId,
                RequestType = "JoinRequest",
                Status = "Pending",
                CreatedAt = DateTime.UtcNow
            };

            await _requestRepository.AddRequestAsync(teamRequest, cancellationToken);

            var loaded = await _requestRepository.GetByIdAsync(teamRequest.RequestId, cancellationToken);
            return ApiResponse<CompetitionTeamRequestResponse>.SuccessResponse(MapToResponse(loaded ?? teamRequest), "Join request submitted successfully.");
        }

        public async Task<ApiResponse<List<CompetitionTeamRequestResponse>>> GetTeamJoinRequestsAsync(int competitionId, int teamId, int captainUserId, CancellationToken cancellationToken = default)
        {
            var team = await _teamRepository.GetByIdAsync(teamId, cancellationToken);
            if (team == null || team.CompetitionId != competitionId)
            {
                return ApiResponse<List<CompetitionTeamRequestResponse>>.FailureResponse("Team not found for the specified competition.");
            }

            if (team.CaptainUserId != captainUserId)
            {
                return ApiResponse<List<CompetitionTeamRequestResponse>>.FailureResponse("Only the team captain can view join requests.");
            }

            var list = await _requestRepository.GetTeamJoinRequestsAsync(teamId, cancellationToken);
            var result = list.Select(MapToResponse).ToList();
            return ApiResponse<List<CompetitionTeamRequestResponse>>.SuccessResponse(result);
        }

        public async Task<ApiResponse<object>> ApproveJoinRequestAsync(int competitionId, int teamId, long requestId, int captainUserId, CancellationToken cancellationToken = default)
        {
            var team = await _teamRepository.GetByIdAsync(teamId, cancellationToken);
            if (team == null || team.CompetitionId != competitionId)
            {
                return ApiResponse<object>.FailureResponse("Team not found for the specified competition.");
            }

            if (team.CaptainUserId != captainUserId)
            {
                return ApiResponse<object>.FailureResponse("Only the team captain can approve join requests.");
            }

            var request = await _requestRepository.GetByIdAsync(requestId, cancellationToken);
            if (request == null || request.RequestType != "JoinRequest" || request.TeamId != teamId)
            {
                return ApiResponse<object>.FailureResponse("Join request not found for this team.");
            }

            if (request.Status != "Pending")
            {
                return ApiResponse<object>.FailureResponse("Only Pending join requests can be approved.");
            }

            bool alreadyInAnyTeam = await _teamRepository.IsUserCaptainOrMemberInCompetitionAsync(competitionId, request.UserId, cancellationToken);
            if (alreadyInAnyTeam)
            {
                return ApiResponse<object>.FailureResponse("User is already a captain or member of an active team in this competition.");
            }

            int memberCount = await _teamRepository.GetTeamMemberCountAsync(teamId, cancellationToken);
            if (memberCount >= 1)
            {
                return ApiResponse<object>.FailureResponse("Team roster is full (maximum 1 ordinary member per team).");
            }

            var member = new CompetitionTeamMember
            {
                TeamId = teamId,
                UserId = request.UserId,
                JoinedAt = DateTime.UtcNow
            };

            await _requestRepository.ApproveJoinRequestWithMemberAsync(request, member, competitionId, request.UserId, captainUserId, cancellationToken);
            return ApiResponse<object>.SuccessResponse(new { }, "Join request approved successfully.");
        }

        public async Task<ApiResponse<object>> RejectJoinRequestAsync(int competitionId, int teamId, long requestId, int captainUserId, RejectTeamRequestDto requestDto, CancellationToken cancellationToken = default)
        {
            var team = await _teamRepository.GetByIdAsync(teamId, cancellationToken);
            if (team == null || team.CompetitionId != competitionId)
            {
                return ApiResponse<object>.FailureResponse("Team not found for the specified competition.");
            }

            if (team.CaptainUserId != captainUserId)
            {
                return ApiResponse<object>.FailureResponse("Only the team captain can reject join requests.");
            }

            var request = await _requestRepository.GetByIdAsync(requestId, cancellationToken);
            if (request == null || request.RequestType != "JoinRequest" || request.TeamId != teamId)
            {
                return ApiResponse<object>.FailureResponse("Join request not found for this team.");
            }

            if (request.Status != "Pending")
            {
                return ApiResponse<object>.FailureResponse("Only Pending join requests can be rejected.");
            }

            request.Status = "Rejected";
            request.Note = requestDto?.Reason?.Trim();
            request.RespondedAt = DateTime.UtcNow;
            request.RespondedByUserId = captainUserId;

            await _requestRepository.UpdateRequestAsync(request, cancellationToken);
            return ApiResponse<object>.SuccessResponse(new { }, "Join request rejected successfully.");
        }

        private static CompetitionTeamRequestResponse MapToResponse(CompetitionTeamRequest r)
        {
            return new CompetitionTeamRequestResponse
            {
                RequestId = r.RequestId,
                TeamId = r.TeamId,
                TeamName = r.Team?.TeamName ?? string.Empty,
                UserId = r.UserId,
                UserName = r.User?.FullName ?? string.Empty,
                CreatedByUserId = r.CreatedByUserId,
                CreatedByName = r.Creator?.FullName ?? string.Empty,
                RequestType = r.RequestType,
                Status = r.Status,
                Note = r.Note,
                CreatedAt = r.CreatedAt,
                RespondedAt = r.RespondedAt,
                RespondedByUserId = r.RespondedByUserId,
                RespondedByName = r.Responder?.FullName
            };
        }
    }
}
