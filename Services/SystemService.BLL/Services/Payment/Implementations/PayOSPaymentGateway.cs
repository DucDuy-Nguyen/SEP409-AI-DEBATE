using System;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;
using PayOS;
using PayOS.Models.V2.PaymentRequests;
using PayOS.Models.Webhooks;
using SystemService.BLL.Services.Payment.Interfaces;

namespace SystemService.BLL.Services.Payment.Implementations
{
    public class PayOSPaymentGateway : IPaymentGateway
    {
        private readonly IConfiguration _configuration;
        private readonly ILogger<PayOSPaymentGateway> _logger;
        private readonly PayOSClient? _client;

        public string ProviderName => "PayOS";

        public PayOSPaymentGateway(IConfiguration configuration, ILogger<PayOSPaymentGateway> logger)
        {
            _configuration = configuration;
            _logger = logger;

            var clientId = _configuration["PayOS:ClientId"] ?? Environment.GetEnvironmentVariable("PAYOS_CLIENT_ID");
            var apiKey = _configuration["PayOS:ApiKey"] ?? Environment.GetEnvironmentVariable("PAYOS_API_KEY");
            var checksumKey = _configuration["PayOS:ChecksumKey"] ?? Environment.GetEnvironmentVariable("PAYOS_CHECKSUM_KEY");

            if (!string.IsNullOrWhiteSpace(clientId) &&
                !string.IsNullOrWhiteSpace(apiKey) &&
                !string.IsNullOrWhiteSpace(checksumKey))
            {
                var options = new PayOSOptions
                {
                    ClientId = clientId,
                    ApiKey = apiKey,
                    ChecksumKey = checksumKey
                };
                _client = new PayOSClient(options);
            }
            else
            {
                _logger.LogWarning("PayOS credentials are not fully configured. Live PayOS integration will require configuration.");
            }
        }

        public async Task<PaymentGatewayResult> CreatePaymentLinkAsync(PaymentLinkArgs args, CancellationToken cancellationToken = default)
        {
            if (_client == null)
            {
                return new PaymentGatewayResult
                {
                    Success = false,
                    ErrorMessage = "PayOS credentials not configured"
                };
            }

            try
            {
                var request = new CreatePaymentLinkRequest
                {
                    OrderCode = args.OrderCode,
                    Amount = (int)args.Amount,
                    Description = args.Description,
                    ReturnUrl = args.ReturnUrl,
                    CancelUrl = args.CancelUrl
                };

                var response = await _client.PaymentRequests.CreateAsync(request);

                return new PaymentGatewayResult
                {
                    Success = true,
                    CheckoutUrl = response.CheckoutUrl,
                    QrCode = response.QrCode
                };
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Failed to create payment link on PayOS for OrderCode {OrderCode}", args.OrderCode);
                return new PaymentGatewayResult
                {
                    Success = false,
                    ErrorMessage = ex.Message
                };
            }
        }

        public async Task<WebhookVerificationResult> VerifyWebhookAsync(Webhook webhook, CancellationToken cancellationToken = default)
        {
            if (_client == null)
            {
                return new WebhookVerificationResult
                {
                    IsValid = false,
                    ErrorMessage = "PayOS credentials not configured"
                };
            }

            try
            {
                var verifiedData = await _client.Webhooks.VerifyAsync(webhook);

                return new WebhookVerificationResult
                {
                    IsValid = true,
                    OrderCode = verifiedData.OrderCode,
                    Amount = verifiedData.Amount,
                    Code = verifiedData.Code,
                    Reference = verifiedData.Reference
                };
            }
            catch (Exception ex)
            {
                _logger.LogWarning(ex, "PayOS webhook signature verification failed");
                return new WebhookVerificationResult
                {
                    IsValid = false,
                    ErrorMessage = ex.Message
                };
            }
        }
    }
}
