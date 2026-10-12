using System.Threading;
using System.Threading.Tasks;
using SystemService.BLL.DTOs.AI;

namespace SystemService.BLL.Services.AI.Interfaces
{
    public interface IAiEvaluatorClient
    {
        Task<EvaluateArgumentResponse?> EvaluateArgumentAsync(EvaluateArgumentRequest req, CancellationToken ct = default);
        Task<EvaluateRoundResponse?> EvaluateRoundAsync(EvaluateRoundRequest req, CancellationToken ct = default);
        Task<EvaluateSessionResponse?> EvaluateSessionAsync(EvaluateSessionRequest req, CancellationToken ct = default);
    }
}
