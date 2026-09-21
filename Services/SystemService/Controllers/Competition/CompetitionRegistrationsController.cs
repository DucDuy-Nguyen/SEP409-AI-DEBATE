using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using System.Security.Claims;
using System.Threading;
using System.Threading.Tasks;
using SystemService.BLL.Common.Responses;
using SystemService.BLL.DTOs.Competition.Registration;
using SystemService.BLL.Services.Competition.Interfaces;

namespace SystemService.Controllers.Competition
{
    [ApiController]
    [Route("api/competitions/{id}/registrations")]
    public class CompetitionRegistrationsController : ControllerBase
    {
        private readonly ICompetitionRegistrationService _registrationService;

        public CompetitionRegistrationsController(ICompetitionRegistrationService registrationService)
        {
            _registrationService = registrationService;
        }

        [Authorize]
        [HttpPost]
        public async Task<IActionResult> Register(int id, CancellationToken cancellationToken)
        {
            var userIdClaim = User.FindFirstValue(ClaimTypes.NameIdentifier);
            if (!int.TryParse(userIdClaim, out int userId))
            {
                return Unauthorized(ApiResponse<CompetitionRegistrationResponse>.FailureResponse("Unauthorized access."));
            }

            var result = await _registrationService.RegisterAsync(id, userId, cancellationToken);
            if (!result.Success)
            {
                return BadRequest(result);
            }
            return Ok(result);
        }

        [HttpGet]
        public async Task<IActionResult> GetList(int id, [FromQuery] string? status, CancellationToken cancellationToken)
        {
            var result = await _registrationService.GetListAsync(id, status, cancellationToken);
            return Ok(result);
        }

        [HttpGet("{registrationId}")]
        public async Task<IActionResult> GetById(int id, long registrationId, CancellationToken cancellationToken)
        {
            var result = await _registrationService.GetByIdAsync(id, registrationId, cancellationToken);
            if (!result.Success)
            {
                return NotFound(result);
            }
            return Ok(result);
        }

        [Authorize]
        [HttpPut("{registrationId}/approve")]
        public async Task<IActionResult> Approve(int id, long registrationId, CancellationToken cancellationToken)
        {
            var userIdClaim = User.FindFirstValue(ClaimTypes.NameIdentifier);
            if (!int.TryParse(userIdClaim, out int userId))
            {
                return Unauthorized(ApiResponse<CompetitionRegistrationResponse>.FailureResponse("Unauthorized access."));
            }

            var result = await _registrationService.ApproveAsync(id, registrationId, userId, cancellationToken);
            if (!result.Success)
            {
                return BadRequest(result);
            }
            return Ok(result);
        }

        [Authorize]
        [HttpPut("{registrationId}/reject")]
        public async Task<IActionResult> Reject(int id, long registrationId, [FromBody] RejectRegistrationRequest request, CancellationToken cancellationToken)
        {
            var userIdClaim = User.FindFirstValue(ClaimTypes.NameIdentifier);
            if (!int.TryParse(userIdClaim, out int userId))
            {
                return Unauthorized(ApiResponse<CompetitionRegistrationResponse>.FailureResponse("Unauthorized access."));
            }

            var result = await _registrationService.RejectAsync(id, registrationId, userId, request, cancellationToken);
            if (!result.Success)
            {
                return BadRequest(result);
            }
            return Ok(result);
        }

        [Authorize]
        [HttpDelete("me")]
        public async Task<IActionResult> CancelMyRegistration(int id, [FromBody] CancelRegistrationRequest request, CancellationToken cancellationToken)
        {
            var userIdClaim = User.FindFirstValue(ClaimTypes.NameIdentifier);
            if (!int.TryParse(userIdClaim, out int userId))
            {
                return Unauthorized(ApiResponse<object>.FailureResponse("Unauthorized access."));
            }

            var result = await _registrationService.CancelMyRegistrationAsync(id, userId, request, cancellationToken);
            if (!result.Success)
            {
                return BadRequest(result);
            }
            return Ok(result);
        }

        [Authorize]
        [HttpPut("{registrationId}/status")]
        public async Task<IActionResult> RemoveParticipant(int id, long registrationId, [FromBody] UpdateRegistrationStatusRequest request, CancellationToken cancellationToken)
        {
            var userIdClaim = User.FindFirstValue(ClaimTypes.NameIdentifier);
            if (!int.TryParse(userIdClaim, out int userId))
            {
                return Unauthorized(ApiResponse<CompetitionRegistrationResponse>.FailureResponse("Unauthorized access."));
            }

            var result = await _registrationService.RemoveParticipantAsync(id, registrationId, userId, request, cancellationToken);
            if (!result.Success)
            {
                return BadRequest(result);
            }
            return Ok(result);
        }
    }
}
