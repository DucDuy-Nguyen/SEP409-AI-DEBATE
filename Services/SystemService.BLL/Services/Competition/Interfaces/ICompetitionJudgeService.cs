using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using SystemService.BLL.Common.Responses;
using SystemService.BLL.DTOs.Competition.Judge;

namespace SystemService.BLL.Services.Competition.Interfaces
{
    public interface ICompetitionJudgeService
    {
        Task<ApiResponse<List<CompetitionJudgeResponse>>> GetListAsync(int competitionId, CancellationToken cancellationToken = default);
    }
}
