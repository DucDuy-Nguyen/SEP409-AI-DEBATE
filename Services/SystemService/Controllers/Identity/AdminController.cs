using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using System.Security.Claims;
using System.Threading;
using System.Threading.Tasks;
using SystemService.BLL.Common.Responses;
using SystemService.BLL.DTOs.Identity.Admin;
using SystemService.BLL.Services.Identity.Interfaces;

namespace SystemService.Controllers.Identity
{
    [ApiController]
    [Route("api/[controller]")]
    [Authorize(Roles = "Admin")]
    public class AdminController : ControllerBase
    {
        private readonly IAdminService _adminService;

        public AdminController(IAdminService adminService)
        {
            _adminService = adminService;
        }

        #region 1. Dashboard

        [HttpGet("dashboard/stats")]
        public async Task<IActionResult> GetDashboardStats(CancellationToken cancellationToken)
        {
            var result = await _adminService.GetDashboardStatsAsync(cancellationToken);
            return Ok(result);
        }

        #endregion

        #region 2. User Management

        [HttpGet("users")]
        public async Task<IActionResult> GetUsers(
            [FromQuery] string? searchTerm,
            [FromQuery] int pageNumber = 1,
            [FromQuery] int pageSize = 10,
            CancellationToken cancellationToken = default)
        {
            var result = await _adminService.GetUsersAsync(searchTerm, pageNumber, pageSize, cancellationToken);
            return Ok(result);
        }

        [HttpGet("users/{id:int}")]
        public async Task<IActionResult> GetUserById(int id, CancellationToken cancellationToken)
        {
            var result = await _adminService.GetUserByIdAsync(id, cancellationToken);
            if (!result.Success)
            {
                return NotFound(result);
            }
            return Ok(result);
        }

        [HttpPatch("users/{id:int}/status")]
        public async Task<IActionResult> UpdateUserStatus(
            int id,
            [FromBody] UpdateUserStatusRequest request,
            CancellationToken cancellationToken)
        {
            var currentAdminId = GetCurrentUserId();
            if (currentAdminId == null)
            {
                return Unauthorized(ApiResponse<object>.FailureResponse("Unauthorized access."));
            }

            var result = await _adminService.UpdateUserStatusAsync(currentAdminId.Value, id, request, cancellationToken);
            if (!result.Success)
            {
                return BadRequest(result);
            }
            return Ok(result);
        }

        #endregion

        #region 3. Role Management

        [HttpGet("roles")]
        public async Task<IActionResult> GetRoles(CancellationToken cancellationToken)
        {
            var result = await _adminService.GetRolesAsync(cancellationToken);
            return Ok(result);
        }

        [HttpPut("users/{id:int}/roles")]
        public async Task<IActionResult> AssignUserRoles(
            int id,
            [FromBody] AssignRolesRequest request,
            CancellationToken cancellationToken)
        {
            var currentAdminId = GetCurrentUserId();
            if (currentAdminId == null)
            {
                return Unauthorized(ApiResponse<object>.FailureResponse("Unauthorized access."));
            }

            var result = await _adminService.AssignUserRolesAsync(currentAdminId.Value, id, request, cancellationToken);
            if (!result.Success)
            {
                return BadRequest(result);
            }
            return Ok(result);
        }

        #endregion

        #region Private Helpers

        private int? GetCurrentUserId()
        {
            var userIdClaim = User.FindFirstValue(ClaimTypes.NameIdentifier);
            if (int.TryParse(userIdClaim, out int userId))
            {
                return userId;
            }
            return null;
        }

        #endregion
    }
}
