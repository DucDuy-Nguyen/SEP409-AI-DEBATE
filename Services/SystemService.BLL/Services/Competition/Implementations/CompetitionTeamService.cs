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
    public class CompetitionTeamService : ICompetitionTeamService
    {
        private readonly ICompetitionTeamRepository _teamRepository;
        private readonly ICompetitionRepository _competitionRepository;
        private readonly ICompetitionRegistrationRepository _registrationRepository;
        private readonly IUserRepository _userRepository;

        public CompetitionTeamService(
            ICompetitionTeamRepository teamRepository,
            ICompetitionRepository competitionRepository,
            ICompetitionRegistrationRepository registrationRepository,
            IUserRepository userRepository)
        {
            _teamRepository = teamRepository;
            _competitionRepository = competitionRepository;
            _registrationRepository = registrationRepository;
            _userRepository = userRepository;
        }

        public async Task<ApiResponse<CompetitionTeamResponse>> CreateTeamAsync(int competitionId, int captainUserId, CreateCompetitionTeamRequest request, CancellationToken cancellationToken = default)
        {
            if (string.IsNullOrWhiteSpace(request.TeamName))
            {
                return ApiResponse<CompetitionTeamResponse>.FailureResponse("TeamName is required.");
            }

            var competition = await _competitionRepository.GetByIdAsync(competitionId, cancellationToken);
            if (competition == null)
            {
                return ApiResponse<CompetitionTeamResponse>.FailureResponse("Competition not found.");
            }

            if (competition.CompetitionType != "TEAM")
            {
                return ApiResponse<CompetitionTeamResponse>.FailureResponse("Teams can only be created for TEAM competitions.");
            }

            bool isAlreadyInTeam = await _teamRepository.IsUserCaptainOrMemberInCompetitionAsync(competitionId, captainUserId, cancellationToken);
            if (isAlreadyInTeam)
            {
                return ApiResponse<CompetitionTeamResponse>.FailureResponse("User is already a captain or member of an active team in this competition.");
            }

            if (competition.MaxParticipants.HasValue)
            {
                int maxTeams = competition.MaxParticipants.Value / 2;
                int activeTeams = await _teamRepository.GetActiveTeamCountAsync(competitionId, cancellationToken);
                if (activeTeams >= maxTeams)
                {
                    return ApiResponse<CompetitionTeamResponse>.FailureResponse("Competition has reached maximum team capacity.");
                }
            }

            var teamNameTrimmed = request.TeamName.Trim();
            bool nameExists = await _teamRepository.IsTeamNameExistsAsync(competitionId, teamNameTrimmed, cancellationToken);
            if (nameExists)
            {
                return ApiResponse<CompetitionTeamResponse>.FailureResponse("Team name already exists in this competition.");
            }

            var team = new CompetitionTeam
            {
                CompetitionId = competitionId,
                TeamName = teamNameTrimmed,
                CaptainUserId = captainUserId,
                Status = "Active",
                CreatedAt = DateTime.UtcNow
            };

            await _teamRepository.AddTeamAsync(team, cancellationToken);

            var response = MapToResponse(team);
            return ApiResponse<CompetitionTeamResponse>.SuccessResponse(response, "Team created successfully.");
        }

        public async Task<ApiResponse<List<CompetitionTeamResponse>>> GetListAsync(int competitionId, CancellationToken cancellationToken = default)
        {
            var teams = await _teamRepository.GetListByCompetitionAsync(competitionId, cancellationToken);
            var result = teams.Select(MapToResponse).ToList();
            return ApiResponse<List<CompetitionTeamResponse>>.SuccessResponse(result);
        }

        public async Task<ApiResponse<CompetitionTeamDetailResponse>> GetByIdAsync(int competitionId, int teamId, CancellationToken cancellationToken = default)
        {
            var team = await _teamRepository.GetWithMembersAsync(teamId, cancellationToken);
            if (team == null || team.CompetitionId != competitionId)
            {
                return ApiResponse<CompetitionTeamDetailResponse>.FailureResponse("Team not found for the specified competition.");
            }

            var response = new CompetitionTeamDetailResponse
            {
                TeamId = team.TeamId,
                CompetitionId = team.CompetitionId,
                TeamName = team.TeamName,
                CaptainUserId = team.CaptainUserId,
                CaptainName = team.Captain?.FullName ?? string.Empty,
                Status = team.Status,
                CreatedAt = team.CreatedAt,
                Members = team.TeamMembers.Select(tm => new CompetitionTeamMemberResponse
                {
                    TeamMemberId = tm.TeamMemberId,
                    UserId = tm.UserId,
                    FullName = tm.User?.FullName ?? string.Empty,
                    Email = tm.User?.Email ?? string.Empty,
                    AvatarUrl = tm.User?.AvatarUrl,
                    JoinedAt = tm.JoinedAt
                }).ToList()
            };

            return ApiResponse<CompetitionTeamDetailResponse>.SuccessResponse(response);
        }

        public async Task<ApiResponse<object>> LeaveTeamAsync(int competitionId, int teamId, int userId, CancellationToken cancellationToken = default)
        {
            var team = await _teamRepository.GetByIdAsync(teamId, cancellationToken);
            if (team == null || team.CompetitionId != competitionId)
            {
                return ApiResponse<object>.FailureResponse("Team not found for the specified competition.");
            }

            if (team.CaptainUserId == userId)
            {
                return ApiResponse<object>.FailureResponse("Team captain cannot leave the team.");
            }

            var member = await _teamRepository.GetTeamMemberAsync(teamId, userId, cancellationToken);
            if (member == null)
            {
                return ApiResponse<object>.FailureResponse("User is not a member of this team.");
            }

            await _teamRepository.RemoveMemberAsync(member, cancellationToken);
            return ApiResponse<object>.SuccessResponse(new { }, "Left team successfully.");
        }

        public async Task<ApiResponse<object>> RemoveMemberAsync(int competitionId, int teamId, int targetUserId, int currentUserId, CancellationToken cancellationToken = default)
        {
            var team = await _teamRepository.GetByIdAsync(teamId, cancellationToken);
            if (team == null || team.CompetitionId != competitionId)
            {
                return ApiResponse<object>.FailureResponse("Team not found for the specified competition.");
            }

            if (team.CaptainUserId != currentUserId)
            {
                return ApiResponse<object>.FailureResponse("Only the team captain can remove members.");
            }

            if (targetUserId == team.CaptainUserId)
            {
                return ApiResponse<object>.FailureResponse("Captain cannot kick themselves.");
            }

            var member = await _teamRepository.GetTeamMemberAsync(teamId, targetUserId, cancellationToken);
            if (member == null)
            {
                return ApiResponse<object>.FailureResponse("Team member record not found.");
            }

            await _teamRepository.RemoveMemberAsync(member, cancellationToken);
            return ApiResponse<object>.SuccessResponse(new { }, "Member removed from team successfully.");
        }

        public async Task<ApiResponse<object>> WithdrawTeamAsync(int competitionId, int teamId, int currentUserId, CancellationToken cancellationToken = default)
        {
            var team = await _teamRepository.GetByIdAsync(teamId, cancellationToken);
            if (team == null || team.CompetitionId != competitionId)
            {
                return ApiResponse<object>.FailureResponse("Team not found for the specified competition.");
            }

            if (team.CaptainUserId != currentUserId)
            {
                return ApiResponse<object>.FailureResponse("Only the team captain can withdraw the team.");
            }

            team.Status = "Withdrawn";
            await _teamRepository.UpdateTeamAsync(team, cancellationToken);

            return ApiResponse<object>.SuccessResponse(new { }, "Team withdrawn successfully.");
        }

        private static CompetitionTeamResponse MapToResponse(CompetitionTeam t)
        {
            return new CompetitionTeamResponse
            {
                TeamId = t.TeamId,
                CompetitionId = t.CompetitionId,
                TeamName = t.TeamName,
                CaptainUserId = t.CaptainUserId,
                Status = t.Status,
                CreatedAt = t.CreatedAt
            };
        }
    }
}
