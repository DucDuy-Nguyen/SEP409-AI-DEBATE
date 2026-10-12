using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using System.Security.Claims;
using System.Threading;
using System.Threading.Tasks;
using SystemService.BLL.Common.Responses;
using SystemService.BLL.DTOs.Debate;
using SystemService.BLL.Services.Debate.Interfaces;

namespace SystemService.Controllers.Debate
{
    [ApiController]
    [Route("api/[controller]")]
    public class TopicsController : ControllerBase
    {
        private readonly ITopicService _topicService;

        public TopicsController(ITopicService topicService)
        {
            _topicService = topicService;
        }

        [HttpGet]
        [AllowAnonymous]
        public async Task<IActionResult> GetTopics(
            [FromQuery] TopicQueryParameters query, CancellationToken cancellationToken)
        {
            var result = await _topicService.GetTopicsAsync(query, cancellationToken);
            return Ok(result);
        }

        [HttpGet("{id:int}")]
        [AllowAnonymous]
        public async Task<IActionResult> GetTopicById(
            int id, CancellationToken cancellationToken)
        {
            var result = await _topicService.GetTopicByIdAsync(id, cancellationToken);
            if (!result.Success)
            {
                return NotFound(result);
            }
            return Ok(result);
        }

        [HttpPost]
        [Authorize]
        public async Task<IActionResult> CreateTopic(
            [FromBody] CreateTopicRequest request, CancellationToken cancellationToken)
        {
            var userId = GetCurrentUserId();
            if (userId == null)
            {
                return Unauthorized(ApiResponse<object>.FailureResponse("Unauthorized access."));
            }

            var result = await _topicService.CreateTopicAsync(userId.Value, request, cancellationToken);
            if (!result.Success)
            {
                return BadRequest(result);
            }
            return CreatedAtAction(nameof(GetTopicById), new { id = result.Data?.TopicId }, result);
        }

        [HttpPatch("{id:int}")]
        [Authorize]
        public async Task<IActionResult> UpdateTopic(
            int id, [FromBody] UpdateTopicRequest request, CancellationToken cancellationToken)
        {
            var result = await _topicService.UpdateTopicAsync(id, request, cancellationToken);
            if (!result.Success)
            {
                return BadRequest(result);
            }
            return Ok(result);
        }

        [HttpDelete("{id:int}")]
        [Authorize]
        public async Task<IActionResult> DeleteTopic(
            int id, CancellationToken cancellationToken)
        {
            var result = await _topicService.DeleteTopicAsync(id, cancellationToken);
            if (!result.Success)
            {
                return BadRequest(result);
            }
            return Ok(result);
        }

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
