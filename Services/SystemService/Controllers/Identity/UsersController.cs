using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using System.Security.Claims;
using System.Threading;
using System.Threading.Tasks;
using SystemService.Common.Responses;
using SystemService.Models.DTOs.Identity.Users;
using SystemService.Services.Identity.Interfaces;

namespace SystemService.Controllers.Identity
{
    [ApiController]
    [Route("api/[controller]")]
    public class UsersController : ControllerBase
    {
        private readonly IUserService _userService;

        public UsersController(IUserService userService)
        {
            _userService = userService;
        }

        [Authorize]
        [HttpGet("me")]
        public async Task<IActionResult> GetMyProfile(CancellationToken cancellationToken)
        {
            var userIdClaim = User.FindFirstValue(ClaimTypes.NameIdentifier);
            if (!int.TryParse(userIdClaim, out int userId))
            {
                return Unauthorized(ApiResponse<UserProfileResponse>.FailureResponse("Unauthorized access."));
            }

            var result = await _userService.GetMyProfileAsync(userId, cancellationToken);
            if (!result.Success)
            {
                return NotFound(result);
            }
            return Ok(result);
        }

        [Authorize]
        [HttpPut("me")]
        public async Task<IActionResult> UpdateMyProfile([FromBody] UpdateProfileRequest request, CancellationToken cancellationToken)
        {
            var userIdClaim = User.FindFirstValue(ClaimTypes.NameIdentifier);
            if (!int.TryParse(userIdClaim, out int userId))
            {
                return Unauthorized(ApiResponse<UserProfileResponse>.FailureResponse("Unauthorized access."));
            }

            var result = await _userService.UpdateMyProfileAsync(userId, request, cancellationToken);
            if (!result.Success)
            {
                return BadRequest(result);
            }
            return Ok(result);
        }
    }
}
