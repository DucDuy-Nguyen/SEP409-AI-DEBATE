using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using SystemService.Common.Responses;

namespace SystemService.Controllers.Identity
{
    [ApiController]
    [Route("api/[controller]")]
    public class AdminController : ControllerBase
    {
        [Authorize(Roles = "Admin")]
        [HttpGet("test")]
        public IActionResult TestAdminAuthorization()
        {
            return Ok(ApiResponse<object>.SuccessResponse(new { }, "Admin authorization successful"));
        }
    }
}
