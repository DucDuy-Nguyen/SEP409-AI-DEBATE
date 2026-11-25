using System.Threading;
using System.Threading.Tasks;
using SystemService.BLL.Common.Responses;
using SystemService.BLL.DTOs.Payment;

namespace SystemService.BLL.Services.Payment.Interfaces
{
    public interface ICreditService
    {
        Task<long> GetRulePriceAsync(string ruleCode, CancellationToken cancellationToken = default);
        Task<ApiResponse<CreditPricesResponse>> GetPricesAsync(CancellationToken cancellationToken = default);
        Task<ApiResponse<CompetitionPriceQuoteResponse>> GetCompetitionPriceQuoteAsync(
            string competitionType,
            int? maxParticipants,
            int? maxTeams = null,
            CancellationToken cancellationToken = default);
        Task<ApiResponse<AiHintResponse>> RequestArgumentHintAsync(
            int userId,
            AiHintRequest request,
            CancellationToken cancellationToken = default);
    }
}
