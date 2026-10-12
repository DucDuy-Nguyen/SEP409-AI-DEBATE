using System.Threading;
using System.Threading.Tasks;
using SystemService.BLL.DTOs.AI;

namespace SystemService.BLL.Services.AI.Interfaces
{
    public interface IAiOpponentClient
    {
        Task<CreateOpponentSessionResponse?> InitCasePlanAsync(CreateOpponentSessionRequest req, CancellationToken ct = default);
        Task<GenerateTurnResponse?> GenerateCounterSpeechAsync(string externalSessionId, GenerateTurnRequest req, CancellationToken ct = default);
    }
}
