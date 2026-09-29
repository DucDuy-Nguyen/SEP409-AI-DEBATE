using System.Threading;
using System.Threading.Tasks;
using SystemService.BLL.Common.Responses;
using SystemService.BLL.DTOs.Payment;

namespace SystemService.BLL.Services.Payment.Interfaces
{
    public interface IRewardService
    {
        Task<ApiResponse<RewardStatusResponse>> GetRewardStatusAsync(int userId, CancellationToken cancellationToken = default);
        Task<ApiResponse<RewardClaimResponse>> ClaimDailyLoginRewardAsync(int userId, CancellationToken cancellationToken = default);
        Task<ApiResponse<RewardClaimResponse?>> ClaimFirstLoginRewardAsync(int userId, CancellationToken cancellationToken = default);
    }
}
