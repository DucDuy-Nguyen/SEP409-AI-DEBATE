using System.Threading;
using System.Threading.Tasks;
using PayOS.Models.Webhooks;
using SystemService.BLL.Common.Responses;
using SystemService.BLL.DTOs.Payment;

namespace SystemService.BLL.Services.Payment.Interfaces
{
    public interface IPaymentService
    {
        Task<ApiResponse<CustomTopUpQuoteResponse>> GetCustomTopUpQuoteAsync(long creditAmount, CancellationToken cancellationToken = default);
        Task<ApiResponse<PaymentLinkResponse>> CreateCustomTopUpPaymentAsync(int userId, CustomTopUpRequest request, CancellationToken cancellationToken = default);
        Task<ApiResponse<PaymentLinkResponse>> CreateTopUpPaymentAsync(int userId, TopUpRequest request, CancellationToken cancellationToken = default);
        Task<ApiResponse<PaymentStatusResponse>> GetPaymentStatusAsync(int userId, long paymentId, CancellationToken cancellationToken = default);
        Task<ApiResponse<object>> ProcessPayOSWebhookAsync(Webhook webhook, CancellationToken cancellationToken = default);
    }
}
