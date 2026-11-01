using System.Threading;
using System.Threading.Tasks;
using SystemService.BLL.Common.Responses;
using SystemService.BLL.DTOs.Competition.Tournament;

namespace SystemService.BLL.Services.Competition.Interfaces;

public interface ICompetitionTournamentService
{
    Task<ApiResponse<BracketResponse>> GenerateBracketAsync(int competitionId, int actorId, CancellationToken ct = default);
    Task<ApiResponse<BracketResponse>> GetBracketAsync(int competitionId, CancellationToken ct = default);
    Task<ApiResponse<object>> AssignJudgeAsync(int competitionId, int matchId, int actorId, int judgeUserId, CancellationToken ct = default);
    Task<ApiResponse<MatchReviewResponse>> GetReviewAsync(int competitionId, int matchId, int actorId, CancellationToken ct = default);
    Task<ApiResponse<object>> FinalizeMatchAsync(int competitionId, int matchId, int actorId, FinalizeMatchRequest request, CancellationToken ct = default);
}
