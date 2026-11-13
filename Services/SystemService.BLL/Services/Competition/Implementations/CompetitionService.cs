using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using SystemService.BLL.Common.Responses;
using SystemService.BLL.Services.Competition;
using SystemService.BLL.DTOs.Competition.Management;
using SystemService.BLL.Services.Competition.Interfaces;
using SystemService.DAL.Entities.Competition;
using SystemService.DAL.Repositories.Competition.Interfaces;
using SystemService.DAL.Repositories.Identity.Interfaces;

namespace SystemService.BLL.Services.Competition.Implementations
{
    public class CompetitionService : ICompetitionService
    {
        private readonly ICompetitionRepository _competitionRepository;
        private readonly IDebateFormatRepository _debateFormatRepository;
        private readonly IUserRepository _userRepository;
        private readonly ICompetitionRegistrationRepository _registrationRepository;
        private readonly ICompetitionTeamRepository _teamRepository;

        public CompetitionService(
            ICompetitionRepository competitionRepository,
            IDebateFormatRepository debateFormatRepository,
            IUserRepository userRepository,
            ICompetitionRegistrationRepository registrationRepository,
            ICompetitionTeamRepository teamRepository)
        {
            _competitionRepository = competitionRepository;
            _debateFormatRepository = debateFormatRepository;
            _userRepository = userRepository;
            _registrationRepository = registrationRepository;
            _teamRepository = teamRepository;
        }

        public async Task<ApiResponse<CompetitionResponse>> CreateAsync(int createdByUserId, CreateCompetitionRequest request, CancellationToken cancellationToken = default)
        {
            var creator = await _userRepository.GetUserWithRolesAsync(createdByUserId, cancellationToken);
            if (creator == null)
            {
                return ApiResponse<CompetitionResponse>.FailureResponse("User not found.");
            }

            if (!creator.IsActive || !creator.UserRoles.Any(ur => ur.Role.RoleName == "Admin" || ur.Role.RoleName == "Lecturer"))
            {
                return ApiResponse<CompetitionResponse>.FailureResponse("Only Admin or Lecturer may create competitions.", CompetitionErrorCodes.Forbidden);
            }

            if (string.IsNullOrWhiteSpace(request.Title))
            {
                return ApiResponse<CompetitionResponse>.FailureResponse("Title is required.");
            }

            var trimmedTitle = request.Title.Trim();
            if (trimmedTitle.Length > 200)
            {
                return ApiResponse<CompetitionResponse>.FailureResponse("Title must not exceed 200 characters.");
            }

            var type = request.CompetitionType?.ToUpperInvariant();
            if (type != "INDIVIDUAL" && type != "TEAM")
            {
                return ApiResponse<CompetitionResponse>.FailureResponse("CompetitionType must be either INDIVIDUAL or TEAM.");
            }

            if (request.FormatId.HasValue)
            {
                if (request.FormatId.Value <= 0)
                {
                    return ApiResponse<CompetitionResponse>.FailureResponse("FormatId must be greater than 0 or null.");
                }

                var formatExists = await _debateFormatRepository.ExistsAsync(request.FormatId.Value, cancellationToken);
                if (!formatExists)
                {
                    return ApiResponse<CompetitionResponse>.FailureResponse($"Debate format with FormatId {request.FormatId.Value} does not exist.");
                }
            }

            if (request.MaxParticipants.HasValue && request.MaxParticipants.Value <= 0)
            {
                return ApiResponse<CompetitionResponse>.FailureResponse("MaxParticipants must be greater than 0 or null.");
            }

            if (type == "TEAM" && request.MaxParticipants.HasValue && request.MaxParticipants.Value % 2 != 0)
            {
                return ApiResponse<CompetitionResponse>.FailureResponse("TEAM MaxParticipants must be even.");
            }

            if (request.RegistrationEnd <= request.RegistrationStart)
            {
                return ApiResponse<CompetitionResponse>.FailureResponse("RegistrationEnd must be after RegistrationStart.");
            }

            if (request.StartDate < request.RegistrationEnd)
            {
                return ApiResponse<CompetitionResponse>.FailureResponse("StartDate must be on or after RegistrationEnd.");
            }

            if (request.EndDate.HasValue && request.EndDate.Value < request.StartDate)
            {
                return ApiResponse<CompetitionResponse>.FailureResponse("EndDate must be on or after StartDate.");
            }

            var competition = new SystemService.DAL.Entities.Competition.Competition
            {
                Title = trimmedTitle,
                Description = request.Description,
                CreatedBy = createdByUserId,
                CompetitionType = type,
                FormatId = request.FormatId,
                MaxParticipants = request.MaxParticipants,
                RegistrationStart = request.RegistrationStart,
                RegistrationEnd = request.RegistrationEnd,
                StartDate = request.StartDate,
                EndDate = request.EndDate,
                Status = "Draft",
                IsPublic = request.IsPublic,
                CreatedAt = DateTime.UtcNow
            };

            var judge = new CompetitionJudge
            {
                UserId = createdByUserId,
                AssignedAt = DateTime.UtcNow
            };

            await _competitionRepository.CreateWithJudgeAsync(competition, judge, cancellationToken);

            var response = MapToResponse(competition);
            return ApiResponse<CompetitionResponse>.SuccessResponse(response, "Competition created successfully.");
        }

        public async Task<ApiResponse<CompetitionResponse>> PatchAsync(int competitionId, int currentUserId, PatchCompetitionRequest request, CancellationToken cancellationToken = default)
        {
            var competition = await _competitionRepository.GetByIdAsync(competitionId, cancellationToken);
            if (competition == null)
            {
                return ApiResponse<CompetitionResponse>.FailureResponse("Competition not found.", CompetitionErrorCodes.NotFound);
            }

            if (competition.CreatedBy != currentUserId)
            {
                return ApiResponse<CompetitionResponse>.FailureResponse("Only the competition creator may manage it.", CompetitionErrorCodes.Forbidden);
            }

            if (competition.Status == "Completed" || competition.Status == "Cancelled")
            {
                return ApiResponse<CompetitionResponse>.FailureResponse("Completed or cancelled competitions cannot be changed.", CompetitionErrorCodes.Conflict);
            }

            var existingRounds = await _competitionRepository.GetRoundsWithMatchesAsync(competitionId, cancellationToken);

            if (!request.HasAnyProperty)
            {
                return ApiResponse<CompetitionResponse>.FailureResponse("At least one field must be provided for update.");
            }

            if (request.HasTitle)
            {
                if (string.IsNullOrWhiteSpace(request.Title))
                {
                    return ApiResponse<CompetitionResponse>.FailureResponse("Title cannot be empty or whitespace.");
                }
                var trimmedTitle = request.Title.Trim();
                if (trimmedTitle.Length > 200)
                {
                    return ApiResponse<CompetitionResponse>.FailureResponse("Title must not exceed 200 characters.");
                }
            }

            if (request.HasFormatId && request.FormatId.HasValue)
            {
                if (request.FormatId.Value <= 0)
                {
                    return ApiResponse<CompetitionResponse>.FailureResponse("FormatId must be greater than 0 or null.");
                }

                var formatExists = await _debateFormatRepository.ExistsAsync(request.FormatId.Value, cancellationToken);
                if (!formatExists)
                {
                    return ApiResponse<CompetitionResponse>.FailureResponse($"Debate format with FormatId {request.FormatId.Value} does not exist.");
                }
            }

            if (request.HasMaxParticipants && request.MaxParticipants.HasValue)
            {
                if (request.MaxParticipants.Value <= 0)
                {
                    return ApiResponse<CompetitionResponse>.FailureResponse("MaxParticipants must be greater than 0 or null.");
                }
            }

            var effectiveMaxParticipants = request.HasMaxParticipants ? request.MaxParticipants : competition.MaxParticipants;
            if (competition.CompetitionType == "TEAM" && effectiveMaxParticipants.HasValue && effectiveMaxParticipants.Value % 2 != 0)
            {
                return ApiResponse<CompetitionResponse>.FailureResponse("TEAM MaxParticipants must be even.");
            }

            if (existingRounds.Count > 0 && (request.HasFormatId || request.HasMaxParticipants || request.HasRegistrationStart || request.HasRegistrationEnd))
            {
                return ApiResponse<CompetitionResponse>.FailureResponse("Bracket-dependent settings cannot change after bracket creation.", CompetitionErrorCodes.Conflict);
            }

            if (request.HasRegistrationStart && !request.RegistrationStart.HasValue)
            {
                return ApiResponse<CompetitionResponse>.FailureResponse("RegistrationStart cannot be null.");
            }

            if (request.HasRegistrationEnd && !request.RegistrationEnd.HasValue)
            {
                return ApiResponse<CompetitionResponse>.FailureResponse("RegistrationEnd cannot be null.");
            }

            if (request.HasStartDate && !request.StartDate.HasValue)
            {
                return ApiResponse<CompetitionResponse>.FailureResponse("StartDate cannot be null.");
            }

            if (request.HasIsPublic && !request.IsPublic.HasValue)
            {
                return ApiResponse<CompetitionResponse>.FailureResponse("IsPublic cannot be null.");
            }

            var effectiveRegistrationStart = request.HasRegistrationStart && request.RegistrationStart.HasValue
                ? request.RegistrationStart.Value
                : competition.RegistrationStart;

            var effectiveRegistrationEnd = request.HasRegistrationEnd && request.RegistrationEnd.HasValue
                ? request.RegistrationEnd.Value
                : competition.RegistrationEnd;

            var effectiveStartDate = request.HasStartDate && request.StartDate.HasValue
                ? request.StartDate.Value
                : competition.StartDate;

            var effectiveEndDate = request.HasEndDate
                ? request.EndDate
                : competition.EndDate;

            if (effectiveRegistrationEnd <= effectiveRegistrationStart)
            {
                return ApiResponse<CompetitionResponse>.FailureResponse("RegistrationEnd must be after RegistrationStart.");
            }

            if (effectiveStartDate < effectiveRegistrationEnd)
            {
                return ApiResponse<CompetitionResponse>.FailureResponse("StartDate must be on or after RegistrationEnd.");
            }

            if (effectiveEndDate.HasValue && effectiveEndDate.Value < effectiveStartDate)
            {
                return ApiResponse<CompetitionResponse>.FailureResponse("EndDate must be on or after StartDate.");
            }

            if (request.HasTitle)
            {
                competition.Title = request.Title!.Trim();
            }

            if (request.HasDescription)
            {
                competition.Description = request.Description;
            }

            if (request.HasFormatId)
            {
                competition.FormatId = request.FormatId;
            }

            if (request.HasMaxParticipants)
            {
                competition.MaxParticipants = request.MaxParticipants;
            }

            if (request.HasRegistrationStart)
            {
                competition.RegistrationStart = request.RegistrationStart!.Value;
            }

            if (request.HasRegistrationEnd)
            {
                competition.RegistrationEnd = request.RegistrationEnd!.Value;
            }

            if (request.HasStartDate)
            {
                competition.StartDate = request.StartDate!.Value;
            }

            if (request.HasEndDate)
            {
                competition.EndDate = request.EndDate;
            }

            if (request.HasIsPublic)
            {
                competition.IsPublic = request.IsPublic!.Value;
            }

            competition.UpdatedAt = DateTime.UtcNow;

            await _competitionRepository.UpdateAsync(competition, cancellationToken);

            var response = MapToResponse(competition);
            return ApiResponse<CompetitionResponse>.SuccessResponse(response, "Competition updated successfully.");
        }

        public async Task<ApiResponse<CompetitionDetailResponse>> GetByIdAsync(int competitionId, CancellationToken cancellationToken = default)
        {
            var competition = await _competitionRepository.GetDetailByIdAsync(competitionId, cancellationToken);
            if (competition == null)
            {
                return ApiResponse<CompetitionDetailResponse>.FailureResponse("Competition not found.");
            }

            var response = new CompetitionDetailResponse
            {
                CompetitionId = competition.CompetitionId,
                Title = competition.Title,
                Description = competition.Description,
                CreatedBy = competition.CreatedBy,
                CreatedByName = competition.Creator?.FullName ?? string.Empty,
                CompetitionType = competition.CompetitionType,
                FormatId = competition.FormatId,
                FormatName = null, // Format name mapped if loaded
                MaxParticipants = competition.MaxParticipants,
                RegistrationStart = competition.RegistrationStart,
                RegistrationEnd = competition.RegistrationEnd,
                StartDate = competition.StartDate,
                EndDate = competition.EndDate,
                Status = competition.Status,
                IsPublic = competition.IsPublic,
                CreatedAt = competition.CreatedAt,
                UpdatedAt = competition.UpdatedAt
            };

            return ApiResponse<CompetitionDetailResponse>.SuccessResponse(response);
        }

        public async Task<ApiResponse<List<CompetitionListItemResponse>>> GetListAsync(CompetitionQueryRequest query, CancellationToken cancellationToken = default)
        {
            var list = await _competitionRepository.GetListAsync(
                query.Status,
                query.CompetitionType,
                query.IsPublic,
                query.Keyword,
                cancellationToken);

            var result = list.Select(c => new CompetitionListItemResponse
            {
                CompetitionId = c.CompetitionId,
                Title = c.Title,
                CompetitionType = c.CompetitionType,
                RegistrationStart = c.RegistrationStart,
                RegistrationEnd = c.RegistrationEnd,
                StartDate = c.StartDate,
                Status = c.Status,
                IsPublic = c.IsPublic
            }).ToList();

            return ApiResponse<List<CompetitionListItemResponse>>.SuccessResponse(result);
        }

        public async Task<ApiResponse<object>> OpenRegistrationAsync(int competitionId, int currentUserId, CancellationToken cancellationToken = default)
        {
            return await UpdateStatusInternalAsync(competitionId, currentUserId, "OpenRegistration", cancellationToken);
        }

        public async Task<ApiResponse<object>> CloseRegistrationAsync(int competitionId, int currentUserId, CancellationToken cancellationToken = default)
        {
            return await UpdateStatusInternalAsync(competitionId, currentUserId, "RegistrationClosed", cancellationToken);
        }

        public async Task<ApiResponse<object>> StartCompetitionAsync(int competitionId, int currentUserId, CancellationToken cancellationToken = default)
        {
            return await UpdateStatusInternalAsync(competitionId, currentUserId, "Ongoing", cancellationToken);
        }

        public async Task<ApiResponse<object>> CompleteCompetitionAsync(int competitionId, int currentUserId, CancellationToken cancellationToken = default)
        {
            return await UpdateStatusInternalAsync(competitionId, currentUserId, "Completed", cancellationToken);
        }

        public async Task<ApiResponse<object>> CancelCompetitionAsync(int competitionId, int currentUserId, CancellationToken cancellationToken = default)
        {
            return await UpdateStatusInternalAsync(competitionId, currentUserId, "Cancelled", cancellationToken);
        }

        private async Task<ApiResponse<object>> UpdateStatusInternalAsync(int competitionId, int currentUserId, string newStatus, CancellationToken cancellationToken)
        {
            var competition = await _competitionRepository.GetByIdAsync(competitionId, cancellationToken);
            if (competition == null)
            {
                return ApiResponse<object>.FailureResponse("Competition not found.", CompetitionErrorCodes.NotFound);
            }

            if (competition.CreatedBy != currentUserId)
            {
                return ApiResponse<object>.FailureResponse("Only the competition creator may manage it.", CompetitionErrorCodes.Forbidden);
            }

            if (competition.Status == "Completed" || competition.Status == "Cancelled")
            {
                return ApiResponse<object>.FailureResponse("Completed or cancelled competitions cannot be reopened.", CompetitionErrorCodes.Conflict);
            }

            var now = DateTime.UtcNow;
            if (newStatus == "OpenRegistration")
            {
                if (competition.Status != "Draft" || now < competition.RegistrationStart || now >= competition.RegistrationEnd)
                    return ApiResponse<object>.FailureResponse("Registration can open only during its scheduled window from Draft.", CompetitionErrorCodes.Conflict);
            }
            else if (newStatus == "RegistrationClosed")
            {
                if (competition.Status != "OpenRegistration")
                    return ApiResponse<object>.FailureResponse("Only open registration can be closed.", CompetitionErrorCodes.Conflict);
            }
            else if (newStatus == "Ongoing")
            {
                if (competition.Status != "RegistrationClosed" || now < competition.StartDate)
                    return ApiResponse<object>.FailureResponse("Competition can start only after registration closes and its start time arrives.", CompetitionErrorCodes.Conflict);

                var rounds = await _competitionRepository.GetRoundsWithMatchesAsync(competitionId, cancellationToken);
                if (!await HasValidStartBracketAsync(competition, rounds, cancellationToken))
                    return ApiResponse<object>.FailureResponse("A valid bracket and eligible entrants are required before start.", CompetitionErrorCodes.Conflict);

                if (!await _competitionRepository.StartWithReadyMatchesAsync(competitionId, cancellationToken))
                    return ApiResponse<object>.FailureResponse("Competition was already started or changed.", CompetitionErrorCodes.Conflict);
                return ApiResponse<object>.SuccessResponse(new { }, "Competition status updated to Ongoing.");
            }
            else if (newStatus == "Completed")
            {
                return ApiResponse<object>.FailureResponse("Official final result and champion confirmation are required before completion.", CompetitionErrorCodes.Conflict);
            }
            else if (newStatus == "Cancelled" && competition.Status != "Draft" && competition.Status != "OpenRegistration" && competition.Status != "RegistrationClosed")
            {
                return ApiResponse<object>.FailureResponse("This competition cannot be cancelled from its current state.", CompetitionErrorCodes.Conflict);
            }

            competition.Status = newStatus;
            competition.UpdatedAt = DateTime.UtcNow;

            await _competitionRepository.UpdateAsync(competition, cancellationToken);
            return ApiResponse<object>.SuccessResponse(new { }, $"Competition status updated to {newStatus}.");
        }

        private async Task<bool> HasValidStartBracketAsync(SystemService.DAL.Entities.Competition.Competition competition, List<CompetitionRound> rounds, CancellationToken cancellationToken)
        {
            if (rounds.Count == 0 || rounds[0].RoundNumber != 1 || rounds.Select(r => r.RoundNumber).Distinct().Count() != rounds.Count)
                return false;

            for (var i = 0; i < rounds.Count; i++)
            {
                if (rounds[i].RoundNumber != i + 1 || rounds[i].Matches.Count == 0 || rounds[i].Matches.Any(m => m.CompetitionId != competition.CompetitionId || m.CompetitionRoundId != rounds[i].CompetitionRoundId))
                    return false;
            }

            var firstMatches = rounds[0].Matches;
            if (firstMatches.Any(m => m.Participants.Count is < 1 or > 2
                || m.Participants.Select(p => p.Side).Distinct().Count() != m.Participants.Count
                || m.Participants.Any(p => p.Side != "PRO" && p.Side != "CON")
                || (m.Participants.Count == 1 && (m.Status != "Bye" || m.DebateSessionId.HasValue
                    || m.WinnerUserId != m.Participants.Single().UserId || m.WinnerTeamId != m.Participants.Single().TeamId))
                || (m.Participants.Count == 2 && m.Status != "Scheduled")))
                return false;

            var bracketSize = firstMatches.Count * 2;
            var entrantCount = firstMatches.Sum(m => m.Participants.Count);
            if (entrantCount < 2 || (bracketSize & (bracketSize - 1)) != 0)
                return false;
            var expectedMatchCount = bracketSize / 2;
            for (var roundIndex = 0; roundIndex < rounds.Count; roundIndex++)
            {
                if (rounds[roundIndex].Matches.Count != expectedMatchCount
                    || (roundIndex > 0 && rounds[roundIndex].Matches.Any(m => m.Participants.Count > 2)))
                    return false;

                var nextIds = roundIndex + 1 < rounds.Count
                    ? rounds[roundIndex + 1].Matches.Select(m => m.CompetitionMatchId).ToHashSet()
                    : new HashSet<int>();
                if (rounds[roundIndex].Matches.Any(m => roundIndex + 1 < rounds.Count
                    ? !m.NextMatchId.HasValue || !nextIds.Contains(m.NextMatchId.Value)
                    : m.NextMatchId.HasValue))
                    return false;

                expectedMatchCount /= 2;
            }
            if (expectedMatchCount != 0)
                return false;

            if (competition.CompetitionType == "INDIVIDUAL")
            {
                var approved = await _registrationRepository.GetListByCompetitionAsync(competition.CompetitionId, "Approved", cancellationToken);
                var eligible = approved.Select(r => r.UserId).ToHashSet();
                var entered = firstMatches.SelectMany(m => m.Participants).Select(p => p.UserId).ToList();
                return eligible.Count == entrantCount && approved.All(r => r.User?.IsActive == true)
                    && (!competition.MaxParticipants.HasValue || eligible.Count <= competition.MaxParticipants.Value)
                    && entered.All(id => id.HasValue) && entered.Select(id => id!.Value).ToHashSet().SetEquals(eligible);
            }

            if (competition.CompetitionType == "TEAM")
            {
                var teams = await _teamRepository.GetListByCompetitionAsync(competition.CompetitionId, cancellationToken);
                var active = teams.Where(t => t.Status == "Active").ToList();
                if (active.Count != entrantCount || (competition.MaxParticipants.HasValue && active.Count * 2 > competition.MaxParticipants.Value))
                    return false;

                var users = new HashSet<int>();
                foreach (var team in active)
                {
                    var full = await _teamRepository.GetWithMembersAsync(team.TeamId, cancellationToken);
                    if (full == null || full.Captain?.IsActive != true || full.TeamMembers.Count != 1
                        || full.TeamMembers.Single().User?.IsActive != true
                        || full.CaptainUserId == full.TeamMembers.Single().UserId
                        || !users.Add(full.CaptainUserId) || !users.Add(full.TeamMembers.Single().UserId))
                        return false;
                }

                var entered = firstMatches.SelectMany(m => m.Participants).Select(p => p.TeamId).ToList();
                return entered.All(id => id.HasValue) && entered.Select(id => id!.Value).ToHashSet().SetEquals(active.Select(t => t.TeamId));
            }

            return false;
        }

        private static CompetitionResponse MapToResponse(SystemService.DAL.Entities.Competition.Competition c)
        {
            return new CompetitionResponse
            {
                CompetitionId = c.CompetitionId,
                Title = c.Title,
                Description = c.Description,
                CreatedBy = c.CreatedBy,
                CompetitionType = c.CompetitionType,
                FormatId = c.FormatId,
                MaxParticipants = c.MaxParticipants,
                RegistrationStart = c.RegistrationStart,
                RegistrationEnd = c.RegistrationEnd,
                StartDate = c.StartDate,
                EndDate = c.EndDate,
                Status = c.Status,
                IsPublic = c.IsPublic,
                CreatedAt = c.CreatedAt,
                UpdatedAt = c.UpdatedAt
            };
        }
    }
}
