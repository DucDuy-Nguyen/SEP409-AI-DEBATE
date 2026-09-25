using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using SystemService.BLL.Common.Responses;
using SystemService.BLL.DTOs.Competition.Management;
using SystemService.BLL.Services.Competition.Interfaces;
using SystemService.DAL.Entities.Competition;
using SystemService.DAL.Repositories.Competition.Interfaces;

namespace SystemService.BLL.Services.Competition.Implementations
{
    public class CompetitionService : ICompetitionService
    {
        private readonly ICompetitionRepository _competitionRepository;

        public CompetitionService(ICompetitionRepository competitionRepository)
        {
            _competitionRepository = competitionRepository;
        }

        public async Task<ApiResponse<CompetitionResponse>> CreateAsync(int createdByUserId, CreateCompetitionRequest request, CancellationToken cancellationToken = default)
        {
            if (string.IsNullOrWhiteSpace(request.Title))
            {
                return ApiResponse<CompetitionResponse>.FailureResponse("Title is required.");
            }

            var type = request.CompetitionType?.ToUpperInvariant();
            if (type != "INDIVIDUAL" && type != "TEAM")
            {
                return ApiResponse<CompetitionResponse>.FailureResponse("CompetitionType must be either INDIVIDUAL or TEAM.");
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
                Title = request.Title.Trim(),
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

        public async Task<ApiResponse<CompetitionResponse>> UpdateAsync(int competitionId, int currentUserId, UpdateCompetitionRequest request, CancellationToken cancellationToken = default)
        {
            var competition = await _competitionRepository.GetByIdAsync(competitionId, cancellationToken);
            if (competition == null)
            {
                return ApiResponse<CompetitionResponse>.FailureResponse("Competition not found.");
            }

            if (string.IsNullOrWhiteSpace(request.Title))
            {
                return ApiResponse<CompetitionResponse>.FailureResponse("Title is required.");
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

            competition.Title = request.Title.Trim();
            competition.Description = request.Description;
            competition.FormatId = request.FormatId;
            competition.MaxParticipants = request.MaxParticipants;
            competition.RegistrationStart = request.RegistrationStart;
            competition.RegistrationEnd = request.RegistrationEnd;
            competition.StartDate = request.StartDate;
            competition.EndDate = request.EndDate;
            competition.IsPublic = request.IsPublic;
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
            return await UpdateStatusInternalAsync(competitionId, "OpenRegistration", cancellationToken);
        }

        public async Task<ApiResponse<object>> CloseRegistrationAsync(int competitionId, int currentUserId, CancellationToken cancellationToken = default)
        {
            return await UpdateStatusInternalAsync(competitionId, "RegistrationClosed", cancellationToken);
        }

        public async Task<ApiResponse<object>> StartCompetitionAsync(int competitionId, int currentUserId, CancellationToken cancellationToken = default)
        {
            return await UpdateStatusInternalAsync(competitionId, "Ongoing", cancellationToken);
        }

        public async Task<ApiResponse<object>> CompleteCompetitionAsync(int competitionId, int currentUserId, CancellationToken cancellationToken = default)
        {
            return await UpdateStatusInternalAsync(competitionId, "Completed", cancellationToken);
        }

        public async Task<ApiResponse<object>> CancelCompetitionAsync(int competitionId, int currentUserId, CancellationToken cancellationToken = default)
        {
            return await UpdateStatusInternalAsync(competitionId, "Cancelled", cancellationToken);
        }

        private async Task<ApiResponse<object>> UpdateStatusInternalAsync(int competitionId, string newStatus, CancellationToken cancellationToken)
        {
            var competition = await _competitionRepository.GetByIdAsync(competitionId, cancellationToken);
            if (competition == null)
            {
                return ApiResponse<object>.FailureResponse("Competition not found.");
            }

            competition.Status = newStatus;
            competition.UpdatedAt = DateTime.UtcNow;

            await _competitionRepository.UpdateAsync(competition, cancellationToken);
            return ApiResponse<object>.SuccessResponse(new { }, $"Competition status updated to {newStatus}.");
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
