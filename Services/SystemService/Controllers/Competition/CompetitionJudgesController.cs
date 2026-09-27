using Microsoft.AspNetCore.Mvc;
using System.Threading;
using System.Threading.Tasks;
using SystemService.BLL.Services.Competition.Interfaces;

namespace SystemService.Controllers.Competition
{
    [ApiController]
    [Route("api/competitions/{id}/judges")]
    public class CompetitionJudgesController : ControllerBase
    {
        private readonly ICompetitionJudgeService _judgeService;

        public CompetitionJudgesController(ICompetitionJudgeService judgeService)
        {
            _judgeService = judgeService;
        }

        [HttpGet]
        public async Task<IActionResult> GetList(int id, CancellationToken cancellationToken)
        {
            var result = await _judgeService.GetListAsync(id, cancellationToken);
            return Ok(result);
        }
    }
}
