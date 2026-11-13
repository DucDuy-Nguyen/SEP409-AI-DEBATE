using System.Security.Claims;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using SystemService.BLL.Common.Responses;
using SystemService.BLL.DTOs.Competition.Tournament;
using SystemService.BLL.Services.Competition.Interfaces;

namespace SystemService.Controllers.Competition;

[ApiController]
[Route("api/competitions/{competitionId:int}")]
public sealed class CompetitionTournamentController : ControllerBase
{
    private readonly ICompetitionTournamentService _service;
    public CompetitionTournamentController(ICompetitionTournamentService service) => _service = service;

    private int? ActorId => int.TryParse(User.FindFirstValue(ClaimTypes.NameIdentifier), out var id) ? id : null;

    [HttpGet("bracket")]
    public async Task<IActionResult> GetBracket(int competitionId, CancellationToken ct)
    {
        var result = await _service.GetBracketAsync(competitionId, ct, ActorId);
        return result.Success ? Ok(result) : CompetitionHttpErrors.Map(this, result);
    }

    [HttpGet("matches/{matchId:int}")]
    public async Task<IActionResult> GetMatchDetail(int competitionId, int matchId, CancellationToken ct)
    {
        var result = await _service.GetMatchDetailAsync(competitionId, matchId, ActorId, ct);
        return result.Success ? Ok(result) : CompetitionHttpErrors.Map(this, result);
    }

    [Authorize]
    [HttpPost("bracket")]
    public async Task<IActionResult> GenerateBracket(int competitionId, CancellationToken ct)
    {
        if (ActorId is not int actor) return Unauthorized(ApiResponse<object>.FailureResponse("Unauthorized access."));
        var result = await _service.GenerateBracketAsync(competitionId, actor, ct);
        return result.Success ? Ok(result) : CompetitionHttpErrors.Map(this, result);
    }

    [Authorize]
    [HttpPut("matches/{matchId:int}/judge")]
    public async Task<IActionResult> AssignJudge(int competitionId, int matchId, [FromBody] AssignJudgeRequest request, CancellationToken ct)
    {
        if (ActorId is not int actor) return Unauthorized(ApiResponse<object>.FailureResponse("Unauthorized access."));
        var result = await _service.AssignJudgeAsync(competitionId, matchId, actor, request.JudgeUserId, ct);
        return result.Success ? Ok(result) : CompetitionHttpErrors.Map(this, result);
    }

    [Authorize]
    [HttpGet("matches/{matchId:int}/review")]
    public async Task<IActionResult> GetReview(int competitionId, int matchId, CancellationToken ct)
    {
        if (ActorId is not int actor) return Unauthorized(ApiResponse<object>.FailureResponse("Unauthorized access."));
        var result = await _service.GetReviewAsync(competitionId, matchId, actor, ct);
        return result.Success ? Ok(result) : CompetitionHttpErrors.Map(this, result);
    }

    [Authorize]
    [HttpPost("matches/{matchId:int}/finalize")]
    public async Task<IActionResult> Finalize(int competitionId, int matchId, [FromBody] FinalizeMatchRequest request, CancellationToken ct)
    {
        if (ActorId is not int actor) return Unauthorized(ApiResponse<object>.FailureResponse("Unauthorized access."));
        var result = await _service.FinalizeMatchAsync(competitionId, matchId, actor, request, ct);
        return result.Success ? Ok(result) : CompetitionHttpErrors.Map(this, result);
    }
}
