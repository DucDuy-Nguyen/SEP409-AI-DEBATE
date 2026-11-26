using System.Threading;
using System.Threading.Tasks;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using SystemService.BLL.DTOs.Identity.Users;
using SystemService.BLL.Services.Identity.Interfaces;

namespace SystemService.Controllers.Identity
{
    [ApiController]
    [Route("api/learners")]
    public class LearnersController : ControllerBase
    {
        private readonly IFeaturedLearnerService _featuredLearnerService;

        public LearnersController(IFeaturedLearnerService featuredLearnerService)
        {
            _featuredLearnerService = featuredLearnerService;
        }

        /// <summary>
        /// Featured learners for the home page (public): ranked by the AI score of their completed debates.
        /// GET api/learners/featured?days=30&amp;limit=5&amp;minDebates=2 (days=0 = all time).
        /// Only public profile fields (name, avatar, stats), never the email.
        /// </summary>
        [AllowAnonymous]
        [HttpGet("featured")]
        public async Task<IActionResult> GetFeatured([FromQuery] FeaturedLearnersQuery query, CancellationToken cancellationToken)
        {
            var result = await _featuredLearnerService.GetFeaturedLearnersAsync(query, cancellationToken);
            return Ok(result);
        }
    }
}
