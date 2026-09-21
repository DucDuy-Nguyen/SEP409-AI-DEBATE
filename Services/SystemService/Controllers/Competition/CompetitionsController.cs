using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using System.Security.Claims;
using System.Threading;
using System.Threading.Tasks;
using SystemService.BLL.Common.Responses;
using SystemService.BLL.DTOs.Competition.Management;
using SystemService.BLL.Services.Competition.Interfaces;

namespace SystemService.Controllers.Competition
{
    [ApiController]
    [Route("api/[controller]")]
    public class CompetitionsController : ControllerBase
    {
        private readonly ICompetitionService _competitionService;

        public CompetitionsController(ICompetitionService competitionService)
        {
            _competitionService = competitionService;
        }

        [Authorize]
        [HttpPost]
        public async Task<IActionResult> Create([FromBody] CreateCompetitionRequest request, CancellationToken cancellationToken)
        {
            var userIdClaim = User.FindFirstValue(ClaimTypes.NameIdentifier);
            if (!int.TryParse(userIdClaim, out int userId))
            {
                return Unauthorized(ApiResponse<CompetitionResponse>.FailureResponse("Unauthorized access."));
            }

            var result = await _competitionService.CreateAsync(userId, request, cancellationToken);
            if (!result.Success)
            {
                return BadRequest(result);
            }
            return Ok(result);
        }

        [HttpGet]
        public async Task<IActionResult> GetList([FromQuery] CompetitionQueryRequest query, CancellationToken cancellationToken)
        {
            var result = await _competitionService.GetListAsync(query, cancellationToken);
            return Ok(result);
        }

        [HttpGet("{id}")]
        public async Task<IActionResult> GetById(int id, CancellationToken cancellationToken)
        {
            var result = await _competitionService.GetByIdAsync(id, cancellationToken);
            if (!result.Success)
            {
                return NotFound(result);
            }
            return Ok(result);
        }

        [Authorize]
        [HttpPut("{id}")]
        public async Task<IActionResult> Update(int id, [FromBody] UpdateCompetitionRequest request, CancellationToken cancellationToken)
        {
            var userIdClaim = User.FindFirstValue(ClaimTypes.NameIdentifier);
            if (!int.TryParse(userIdClaim, out int userId))
            {
                return Unauthorized(ApiResponse<CompetitionResponse>.FailureResponse("Unauthorized access."));
            }

            var result = await _competitionService.UpdateAsync(id, userId, request, cancellationToken);
            if (!result.Success)
            {
                return BadRequest(result);
            }
            return Ok(result);
        }

        [Authorize]
        [HttpPost("{id}/open-registration")]
        public async Task<IActionResult> OpenRegistration(int id, CancellationToken cancellationToken)
        {
            var userIdClaim = User.FindFirstValue(ClaimTypes.NameIdentifier);
            if (!int.TryParse(userIdClaim, out int userId))
            {
                return Unauthorized(ApiResponse<object>.FailureResponse("Unauthorized access."));
            }

            var result = await _competitionService.OpenRegistrationAsync(id, userId, cancellationToken);
            if (!result.Success)
            {
                return BadRequest(result);
            }
            return Ok(result);
        }

        [Authorize]
        [HttpPost("{id}/close-registration")]
        public async Task<IActionResult> CloseRegistration(int id, CancellationToken cancellationToken)
        {
            var userIdClaim = User.FindFirstValue(ClaimTypes.NameIdentifier);
            if (!int.TryParse(userIdClaim, out int userId))
            {
                return Unauthorized(ApiResponse<object>.FailureResponse("Unauthorized access."));
            }

            var result = await _competitionService.CloseRegistrationAsync(id, userId, cancellationToken);
            if (!result.Success)
            {
                return BadRequest(result);
            }
            return Ok(result);
        }

        [Authorize]
        [HttpPost("{id}/start")]
        public async Task<IActionResult> Start(int id, CancellationToken cancellationToken)
        {
            var userIdClaim = User.FindFirstValue(ClaimTypes.NameIdentifier);
            if (!int.TryParse(userIdClaim, out int userId))
            {
                return Unauthorized(ApiResponse<object>.FailureResponse("Unauthorized access."));
            }

            var result = await _competitionService.StartCompetitionAsync(id, userId, cancellationToken);
            if (!result.Success)
            {
                return BadRequest(result);
            }
            return Ok(result);
        }

        [Authorize]
        [HttpPost("{id}/complete")]
        public async Task<IActionResult> Complete(int id, CancellationToken cancellationToken)
        {
            var userIdClaim = User.FindFirstValue(ClaimTypes.NameIdentifier);
            if (!int.TryParse(userIdClaim, out int userId))
            {
                return Unauthorized(ApiResponse<object>.FailureResponse("Unauthorized access."));
            }

            var result = await _competitionService.CompleteCompetitionAsync(id, userId, cancellationToken);
            if (!result.Success)
            {
                return BadRequest(result);
            }
            return Ok(result);
        }

        [Authorize]
        [HttpPost("{id}/cancel")]
        public async Task<IActionResult> Cancel(int id, CancellationToken cancellationToken)
        {
            var userIdClaim = User.FindFirstValue(ClaimTypes.NameIdentifier);
            if (!int.TryParse(userIdClaim, out int userId))
            {
                return Unauthorized(ApiResponse<object>.FailureResponse("Unauthorized access."));
            }

            var result = await _competitionService.CancelCompetitionAsync(id, userId, cancellationToken);
            if (!result.Success)
            {
                return BadRequest(result);
            }
            return Ok(result);
        }
    }
}
