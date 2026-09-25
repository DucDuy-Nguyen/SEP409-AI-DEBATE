using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using SystemService.BLL.Common.Responses;
using SystemService.BLL.DTOs.Competition.Registration;
using SystemService.BLL.Services.Competition.Interfaces;
using SystemService.DAL.Entities.Competition;
using SystemService.DAL.Repositories.Competition.Interfaces;

namespace SystemService.BLL.Services.Competition.Implementations
{
    public class CompetitionRegistrationService : ICompetitionRegistrationService
    {
        private readonly ICompetitionRegistrationRepository _registrationRepository;
        private readonly ICompetitionRepository _competitionRepository;

        public CompetitionRegistrationService(
            ICompetitionRegistrationRepository registrationRepository,
            ICompetitionRepository competitionRepository)
        {
            _registrationRepository = registrationRepository;
            _competitionRepository = competitionRepository;
        }

        public async Task<ApiResponse<CompetitionRegistrationResponse>> RegisterAsync(int competitionId, int currentUserId, CancellationToken cancellationToken = default)
        {
            var competition = await _competitionRepository.GetByIdAsync(competitionId, cancellationToken);
            if (competition == null)
            {
                return ApiResponse<CompetitionRegistrationResponse>.FailureResponse("Competition not found.");
            }

            if (competition.CompetitionType != "INDIVIDUAL")
            {
                return ApiResponse<CompetitionRegistrationResponse>.FailureResponse("Individual registration is only allowed for INDIVIDUAL competitions.");
            }

            if (competition.Status != "OpenRegistration")
            {
                return ApiResponse<CompetitionRegistrationResponse>.FailureResponse("Registration is not open for this competition.");
            }

            var existing = await _registrationRepository.GetByCompetitionAndUserAsync(competitionId, currentUserId, cancellationToken);
            if (existing != null)
            {
                return ApiResponse<CompetitionRegistrationResponse>.FailureResponse("User has already registered for this competition.");
            }

            var registration = new CompetitionRegistration
            {
                CompetitionId = competitionId,
                UserId = currentUserId,
                Status = "Pending",
                RegisteredAt = DateTime.UtcNow
            };

            await _registrationRepository.AddAsync(registration, cancellationToken);

            var loaded = await _registrationRepository.GetByIdAsync(registration.RegistrationId, cancellationToken);
            var response = MapToResponse(loaded ?? registration);
            return ApiResponse<CompetitionRegistrationResponse>.SuccessResponse(response, "Registration submitted successfully.");
        }

        public async Task<ApiResponse<List<CompetitionRegistrationResponse>>> GetListAsync(int competitionId, string? status, CancellationToken cancellationToken = default)
        {
            var list = await _registrationRepository.GetListByCompetitionAsync(competitionId, status, cancellationToken);
            var result = list.Select(MapToResponse).ToList();
            return ApiResponse<List<CompetitionRegistrationResponse>>.SuccessResponse(result);
        }

        public async Task<ApiResponse<CompetitionRegistrationResponse>> GetByIdAsync(int competitionId, long registrationId, CancellationToken cancellationToken = default)
        {
            var registration = await _registrationRepository.GetByIdAsync(registrationId, cancellationToken);
            if (registration == null || registration.CompetitionId != competitionId)
            {
                return ApiResponse<CompetitionRegistrationResponse>.FailureResponse("Registration not found for the specified competition.");
            }

            return ApiResponse<CompetitionRegistrationResponse>.SuccessResponse(MapToResponse(registration));
        }

        public async Task<ApiResponse<CompetitionRegistrationResponse>> ApproveAsync(int competitionId, long registrationId, int reviewerUserId, CancellationToken cancellationToken = default)
        {
            var registration = await _registrationRepository.GetByIdAsync(registrationId, cancellationToken);
            if (registration == null || registration.CompetitionId != competitionId)
            {
                return ApiResponse<CompetitionRegistrationResponse>.FailureResponse("Registration not found for the specified competition.");
            }

            if (registration.Status != "Pending")
            {
                return ApiResponse<CompetitionRegistrationResponse>.FailureResponse("Only Pending registrations can be approved.");
            }

            registration.Status = "Approved";
            registration.ReviewedBy = reviewerUserId;
            registration.ReviewedAt = DateTime.UtcNow;

            await _registrationRepository.UpdateAsync(registration, cancellationToken);
            return ApiResponse<CompetitionRegistrationResponse>.SuccessResponse(MapToResponse(registration), "Registration approved successfully.");
        }

        public async Task<ApiResponse<CompetitionRegistrationResponse>> RejectAsync(int competitionId, long registrationId, int reviewerUserId, RejectRegistrationRequest request, CancellationToken cancellationToken = default)
        {
            if (string.IsNullOrWhiteSpace(request.Reason))
            {
                return ApiResponse<CompetitionRegistrationResponse>.FailureResponse("Reason is required.");
            }

            var registration = await _registrationRepository.GetByIdAsync(registrationId, cancellationToken);
            if (registration == null || registration.CompetitionId != competitionId)
            {
                return ApiResponse<CompetitionRegistrationResponse>.FailureResponse("Registration not found for the specified competition.");
            }

            if (registration.Status != "Pending")
            {
                return ApiResponse<CompetitionRegistrationResponse>.FailureResponse("Only Pending registrations can be rejected.");
            }

            registration.Status = "Rejected";
            registration.Note = request.Reason.Trim();
            registration.ReviewedBy = reviewerUserId;
            registration.ReviewedAt = DateTime.UtcNow;

            await _registrationRepository.UpdateAsync(registration, cancellationToken);
            return ApiResponse<CompetitionRegistrationResponse>.SuccessResponse(MapToResponse(registration), "Registration rejected successfully.");
        }

        public async Task<ApiResponse<object>> CancelMyRegistrationAsync(int competitionId, int currentUserId, CancelRegistrationRequest request, CancellationToken cancellationToken = default)
        {
            if (string.IsNullOrWhiteSpace(request.Reason))
            {
                return ApiResponse<object>.FailureResponse("Reason is required.");
            }

            var registration = await _registrationRepository.GetByCompetitionAndUserAsync(competitionId, currentUserId, cancellationToken);
            if (registration == null)
            {
                return ApiResponse<object>.FailureResponse("Registration not found.");
            }

            if (registration.Status != "Pending" && registration.Status != "Approved")
            {
                return ApiResponse<object>.FailureResponse("Only Pending or Approved registrations can be cancelled.");
            }

            bool wasApproved = (registration.Status == "Approved");

            registration.Status = "Cancelled";
            registration.Note = request.Reason.Trim();

            await _registrationRepository.UpdateAsync(registration, cancellationToken);

            if (wasApproved)
            {
                // TODO: Notify competition judge when notification module is implemented.
            }

            return ApiResponse<object>.SuccessResponse(new { }, "Registration cancelled successfully.");
        }

        public async Task<ApiResponse<CompetitionRegistrationResponse>> RemoveParticipantAsync(int competitionId, long registrationId, int operatorUserId, UpdateRegistrationStatusRequest request, CancellationToken cancellationToken = default)
        {
            if (string.IsNullOrWhiteSpace(request.Reason))
            {
                return ApiResponse<CompetitionRegistrationResponse>.FailureResponse("Reason is required.");
            }

            var registration = await _registrationRepository.GetByIdAsync(registrationId, cancellationToken);
            if (registration == null || registration.CompetitionId != competitionId)
            {
                return ApiResponse<CompetitionRegistrationResponse>.FailureResponse("Registration not found for the specified competition.");
            }

            if (registration.Status != "Approved")
            {
                return ApiResponse<CompetitionRegistrationResponse>.FailureResponse("Only Approved registrations can be removed.");
            }

            registration.Status = "Cancelled";
            registration.Note = request.Reason.Trim();
            registration.ReviewedBy = operatorUserId;
            registration.ReviewedAt = DateTime.UtcNow;

            await _registrationRepository.UpdateAsync(registration, cancellationToken);
            return ApiResponse<CompetitionRegistrationResponse>.SuccessResponse(MapToResponse(registration), "Participant removed successfully.");
        }

        private static CompetitionRegistrationResponse MapToResponse(CompetitionRegistration r)
        {
            return new CompetitionRegistrationResponse
            {
                RegistrationId = r.RegistrationId,
                CompetitionId = r.CompetitionId,
                UserId = r.UserId,
                UserName = r.User?.FullName ?? string.Empty,
                UserEmail = r.User?.Email ?? string.Empty,
                Status = r.Status,
                Note = r.Note,
                RegisteredAt = r.RegisteredAt,
                ReviewedBy = r.ReviewedBy,
                ReviewedByName = r.Reviewer?.FullName,
                ReviewedAt = r.ReviewedAt
            };
        }
    }
}
