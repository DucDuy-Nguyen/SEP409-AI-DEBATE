using System;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using SystemService.BLL.DTOs.KnowledgeBase;
using SystemService.BLL.Services.KnowledgeBase.Interfaces;

namespace SystemService.Controllers
{
    [ApiController]
    [Route("api/knowledge-base")]
    [Authorize(Roles = "Organizer,Admin")]
    public class KnowledgeBaseController : ControllerBase
    {
        private readonly IKnowledgeBaseService _knowledgeBaseService;

        public KnowledgeBaseController(IKnowledgeBaseService knowledgeBaseService)
        {
            _knowledgeBaseService = knowledgeBaseService;
        }

        [HttpGet("stats")]
        public async Task<IActionResult> GetStats(CancellationToken cancellationToken)
        {
            var (code, body) = await _knowledgeBaseService.GetStatsAsync(cancellationToken);
            return StatusCode(code, body);
        }

        [HttpGet("sources")]
        public async Task<IActionResult> ListSources(
            [FromQuery] string? topic,
            [FromQuery] int page = 1,
            [FromQuery] int pageSize = 20,
            CancellationToken cancellationToken = default)
        {
            var (code, body) = await _knowledgeBaseService.ListSourcesAsync(topic, page, pageSize, cancellationToken);
            return StatusCode(code, body);
        }

        [HttpPost("sources")]
        public async Task<IActionResult> CreateSource(
            [FromBody] CreateKnowledgeSourceRequest request,
            CancellationToken cancellationToken)
        {
            var (code, body) = await _knowledgeBaseService.CreateSourceAsync(request, cancellationToken);
            return StatusCode(code, body);
        }

        [HttpDelete("sources/{sourceId:guid}")]
        public async Task<IActionResult> DeleteSource(Guid sourceId, CancellationToken cancellationToken)
        {
            var (code, body) = await _knowledgeBaseService.DeleteSourceAsync(sourceId, cancellationToken);
            return StatusCode(code, body);
        }

        [HttpGet("facts")]
        public async Task<IActionResult> ListFacts(
            [FromQuery] string? topic,
            [FromQuery] string? status,
            [FromQuery] Guid? sourceId,
            [FromQuery] string? q,
            [FromQuery] int page = 1,
            [FromQuery] int pageSize = 20,
            CancellationToken cancellationToken = default)
        {
            var (code, body) = await _knowledgeBaseService.ListFactsAsync(
                topic, status, sourceId, q, page, pageSize, cancellationToken);
            return StatusCode(code, body);
        }

        [HttpPatch("facts/{factId:guid}")]
        public async Task<IActionResult> UpdateFact(
            Guid factId,
            [FromBody] UpdateFactRequest request,
            CancellationToken cancellationToken)
        {
            var (code, body) = await _knowledgeBaseService.UpdateFactAsync(factId, request, cancellationToken);
            return StatusCode(code, body);
        }

        [HttpPatch("facts/{factId:guid}/status")]
        public async Task<IActionResult> UpdateFactStatus(
            Guid factId,
            [FromBody] UpdateFactStatusRequest request,
            CancellationToken cancellationToken)
        {
            var (code, body) = await _knowledgeBaseService.UpdateFactStatusAsync(factId, request, cancellationToken);
            return StatusCode(code, body);
        }

        [HttpPost("facts/batch-status")]
        public async Task<IActionResult> BatchUpdateFactStatus(
            [FromBody] BatchUpdateFactStatusRequest request,
            CancellationToken cancellationToken)
        {
            var (code, body) = await _knowledgeBaseService.BatchUpdateFactStatusAsync(request, cancellationToken);
            return StatusCode(code, body);
        }

        [HttpDelete("facts/{factId:guid}")]
        public async Task<IActionResult> DeleteFact(Guid factId, CancellationToken cancellationToken)
        {
            var (code, body) = await _knowledgeBaseService.DeleteFactAsync(factId, cancellationToken);
            return StatusCode(code, body);
        }
    }
}

