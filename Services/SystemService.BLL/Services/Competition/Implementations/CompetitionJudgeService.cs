using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using SystemService.BLL.Common.Responses;
using SystemService.BLL.DTOs.Competition.Judge;
using SystemService.BLL.Services.Competition.Interfaces;
using SystemService.DAL.Repositories.Competition.Interfaces;

namespace SystemService.BLL.Services.Competition.Implementations
{
    public class CompetitionJudgeService : ICompetitionJudgeService
    {
        private readonly ICompetitionJudgeRepository _judgeRepository;

        public CompetitionJudgeService(ICompetitionJudgeRepository judgeRepository)
        {
            _judgeRepository = judgeRepository;
        }

        public async Task<ApiResponse<List<CompetitionJudgeResponse>>> GetListAsync(int competitionId, CancellationToken cancellationToken = default)
        {
            var judges = await _judgeRepository.GetListByCompetitionAsync(competitionId, cancellationToken);
            var result = judges.Select(j => new CompetitionJudgeResponse
            {
                CompetitionJudgeId = j.CompetitionJudgeId,
                CompetitionId = j.CompetitionId,
                UserId = j.UserId,
                FullName = j.User?.FullName ?? string.Empty,
                Email = j.User?.Email ?? string.Empty,
                AssignedAt = j.AssignedAt
            }).ToList();

            return ApiResponse<List<CompetitionJudgeResponse>>.SuccessResponse(result);
        }
    }
}
