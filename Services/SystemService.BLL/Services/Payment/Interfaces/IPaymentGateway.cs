using System.Threading;
using System.Threading.Tasks;
using PayOS.Models.Webhooks;

namespace SystemService.BLL.Services.Payment.Interfaces
{
    public class PaymentLinkArgs
    {
        public long OrderCode { get; set; }
        public decimal Amount { get; set; }
        public string Description { get; set; } = string.Empty;
        public string ReturnUrl { get; set; } = string.Empty;
        public string CancelUrl { get; set; } = string.Empty;
    }

    public class PaymentGatewayResult
    {
        public bool Success { get; set; }
        public string? CheckoutUrl { get; set; }
        public string? QrCode { get; set; }
        public string? ErrorMessage { get; set; }
    }

    public class WebhookVerificationResult
    {
        public bool IsValid { get; set; }
        public long OrderCode { get; set; }
        public decimal Amount { get; set; }
        public string? Code { get; set; }
        public string? Reference { get; set; }
        public string? ErrorMessage { get; set; }
    }

    public interface IPaymentGateway
    {
        string ProviderName { get; }
        Task<PaymentGatewayResult> CreatePaymentLinkAsync(PaymentLinkArgs args, CancellationToken cancellationToken = default);
        Task<WebhookVerificationResult> VerifyWebhookAsync(Webhook webhook, CancellationToken cancellationToken = default);
    }
}
