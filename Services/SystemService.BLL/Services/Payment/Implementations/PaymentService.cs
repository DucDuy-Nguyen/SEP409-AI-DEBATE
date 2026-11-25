using System;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;
using PayOS.Models.Webhooks;
using SystemService.BLL.Common.Responses;
using SystemService.BLL.DTOs.Payment;
using SystemService.BLL.Services.Payment.Interfaces;
using SystemService.DAL.Context;
using SystemService.DAL.Entities.Payment;
using SystemService.DAL.Repositories.Payment.Interfaces;

namespace SystemService.BLL.Services.Payment.Implementations
{
    public class PaymentService : IPaymentService
    {
        private readonly SystemDbContext _context;
        private readonly IWalletRepository _walletRepository;
        private readonly ICreditPackageRepository _packageRepository;
        private readonly IPaymentRepository _paymentRepository;
        private readonly IPaymentGateway _paymentGateway;
        private readonly IConfiguration _configuration;
        private readonly ILogger<PaymentService> _logger;

        public PaymentService(
            SystemDbContext context,
            IWalletRepository walletRepository,
            ICreditPackageRepository packageRepository,
            IPaymentRepository paymentRepository,
            IPaymentGateway paymentGateway,
            IConfiguration configuration,
            ILogger<PaymentService> logger)
        {
            _context = context;
            _walletRepository = walletRepository;
            _packageRepository = packageRepository;
            _paymentRepository = paymentRepository;
            _paymentGateway = paymentGateway;
            _configuration = configuration;
            _logger = logger;
        }

        public async Task<ApiResponse<PaymentLinkResponse>> CreateTopUpPaymentAsync(int userId, TopUpRequest request, CancellationToken cancellationToken = default)
        {
            var wallet = await _walletRepository.GetOrCreateWalletByUserIdAsync(userId, cancellationToken);

            var package = await _packageRepository.GetActiveByIdAsync(request.PackageId, cancellationToken);
            if (package == null)
            {
                return ApiResponse<PaymentLinkResponse>.FailureResponse("Credit package not found or is currently inactive.");
            }

            // Snapshot price and credit amounts
            decimal priceSnapshot = package.Price;
            long creditAmountSnapshot = package.CreditAmount + package.BonusCredit;

            // Generate unique OrderCode for PayOS (safe integer/long)
            long orderCode = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();

            var payment = new PaymentTransaction
            {
                UserId = userId,
                WalletId = wallet.WalletId,
                PackageId = package.PackageId,
                Amount = priceSnapshot,
                Currency = package.Currency,
                CreditAmount = creditAmountSnapshot,
                Provider = _paymentGateway.ProviderName,
                ProviderOrderCode = orderCode,
                Status = "Pending",
                CreatedAt = DateTime.UtcNow
            };

            await _paymentRepository.CreateAsync(payment, cancellationToken);
            var allowedOrigins = new HashSet<string>(
                StringComparer.OrdinalIgnoreCase
            )
            {
                "http://localhost:5173",
                "http://localhost:5174"
            };

            var configuredOrigin = _configuration["PayOS:FrontendOrigin"]?.Trim().TrimEnd('/');
            if (!string.IsNullOrWhiteSpace(configuredOrigin))
            {
                allowedOrigins.Add(configuredOrigin);
            }

            var frontendOrigin = request.FrontendOrigin?.Trim().TrimEnd('/');

            if (string.IsNullOrWhiteSpace(frontendOrigin))
            {
                frontendOrigin = configuredOrigin;
            }

if (string.IsNullOrWhiteSpace(frontendOrigin) ||
    !allowedOrigins.Contains(frontendOrigin))
{
    return ApiResponse<PaymentLinkResponse>.FailureResponse(
        "Invalid frontend origin."
    );
}

var returnUrl = $"{frontendOrigin}/payment/success";
var cancelUrl = $"{frontendOrigin}/payment/cancel";
            var gatewayResult = await _paymentGateway.CreatePaymentLinkAsync(new PaymentLinkArgs
            {
                OrderCode = orderCode,
                Amount = priceSnapshot,
                Description = $"TopUp {package.PackageCode}",
                ReturnUrl = returnUrl,
                CancelUrl = cancelUrl
            }, cancellationToken);

            var response = new PaymentLinkResponse
            {
                PaymentId = payment.PaymentId,
                ProviderOrderCode = payment.ProviderOrderCode,
                Amount = payment.Amount,
                Currency = payment.Currency,
                CreditAmount = payment.CreditAmount,
                Provider = payment.Provider,
                Status = payment.Status,
                CheckoutUrl = gatewayResult.CheckoutUrl,
                QrCode = gatewayResult.QrCode
            };

            if (!gatewayResult.Success)
            {
                _logger.LogWarning("Payment link creation returned warning/error: {Error}", gatewayResult.ErrorMessage);
                return ApiResponse<PaymentLinkResponse>.SuccessResponse(response, $"Payment created pending gateway confirmation: {gatewayResult.ErrorMessage}");
            }

            return ApiResponse<PaymentLinkResponse>.SuccessResponse(response, "Payment link created successfully.");
        }

        public async Task<ApiResponse<PaymentStatusResponse>> GetPaymentStatusAsync(int userId, long paymentId, CancellationToken cancellationToken = default)
        {
            var payment = await _paymentRepository.GetByIdAsync(paymentId, cancellationToken);
            if (payment == null)
            {
                return ApiResponse<PaymentStatusResponse>.FailureResponse("Payment not found.");
            }

            if (payment.UserId != userId)
            {
                return ApiResponse<PaymentStatusResponse>.FailureResponse("Access denied.");
            }

            var response = new PaymentStatusResponse
            {
                PaymentId = payment.PaymentId,
                PackageCode = payment.Package?.PackageCode,
                PackageName = payment.Package?.PackageName,
                Amount = payment.Amount,
                Currency = payment.Currency,
                CreditAmount = payment.CreditAmount,
                Provider = payment.Provider,
                ProviderOrderCode = payment.ProviderOrderCode,
                Status = payment.Status,
                CreatedAt = payment.CreatedAt,
                PaidAt = payment.PaidAt,
                CancelledAt = payment.CancelledAt,
                ExpiredAt = payment.ExpiredAt
            };

            return ApiResponse<PaymentStatusResponse>.SuccessResponse(response);
        }

        public async Task<ApiResponse<object>> ProcessPayOSWebhookAsync(Webhook webhook, CancellationToken cancellationToken = default)
        {
            var verification = await _paymentGateway.VerifyWebhookAsync(webhook, cancellationToken);
            if (!verification.IsValid)
            {
                _logger.LogWarning("Invalid PayOS webhook signature: {Error}", verification.ErrorMessage);
                return ApiResponse<object>.FailureResponse($"Invalid webhook signature: {verification.ErrorMessage}");
            }

            // Begin atomic transaction for idempotent settlement
            using var transaction = await _context.Database.BeginTransactionAsync(cancellationToken);
            try
            {
                var payment = await _paymentRepository.GetByProviderOrderCodeForUpdateAsync(_paymentGateway.ProviderName, verification.OrderCode, cancellationToken);
                if (payment == null)
                {
                    _logger.LogWarning("PaymentTransaction not found for ProviderOrderCode {OrderCode}", verification.OrderCode);
                    await transaction.RollbackAsync(cancellationToken);
                    return ApiResponse<object>.FailureResponse($"Payment transaction not found for order code {verification.OrderCode}.");
                }

                // Idempotency check: if already Paid, acknowledge without duplicate credit
                if (payment.Status == "Paid")
                {
                    _logger.LogInformation("PaymentTransaction {PaymentId} is already Paid. Idempotent return.", payment.PaymentId);
                    await transaction.CommitAsync(cancellationToken);
                    return ApiResponse<object>.SuccessResponse(new { }, "Payment already settled.");
                }

                // Do not credit cancelled/expired/failed transactions
                if (payment.Status is "Cancelled" or "Expired" or "Failed")
                {
                    _logger.LogWarning("PaymentTransaction {PaymentId} has terminal status {Status}. Ignoring settlement.", payment.PaymentId, payment.Status);
                    await transaction.RollbackAsync(cancellationToken);
                    return ApiResponse<object>.FailureResponse($"Payment transaction is {payment.Status} and cannot be settled.");
                }

                // Verify PayOS payment result code ("00" means success)
                if (!string.Equals(verification.Code, "00", StringComparison.OrdinalIgnoreCase))
                {
                    payment.Status = "Failed";
                    await _paymentRepository.UpdateAsync(payment, cancellationToken);
                    await transaction.CommitAsync(cancellationToken);
                    _logger.LogWarning("PayOS webhook for OrderCode {OrderCode} returned non-success code {Code}.", verification.OrderCode, verification.Code);
                    return ApiResponse<object>.FailureResponse($"Payment was not successful (Code: {verification.Code}).");
                }

                // Server-side amount verification against snapshot
                if (verification.Amount > 0 && verification.Amount != payment.Amount)
                {
                    _logger.LogWarning("PayOS webhook amount mismatch for OrderCode {OrderCode}: expected {Expected}, got {Actual}.",
                        verification.OrderCode, payment.Amount, verification.Amount);
                    await transaction.RollbackAsync(cancellationToken);
                    return ApiResponse<object>.FailureResponse("Webhook payment amount does not match expected package price.");
                }

                // Settle payment
                payment.Status = "Paid";
                payment.PaidAt = DateTime.UtcNow;
                if (!string.IsNullOrWhiteSpace(verification.Reference))
                {
                    payment.ProviderTransactionId = verification.Reference;
                }
                await _paymentRepository.UpdateAsync(payment, cancellationToken);

                // Lock wallet and credit balance
                var wallet = await _walletRepository.GetByIdForUpdateAsync(payment.WalletId, cancellationToken);
                if (wallet == null)
                {
                    throw new InvalidOperationException($"Wallet {payment.WalletId} not found for payment {payment.PaymentId}.");
                }

                // Secondary idempotency guard against duplicate ledger entry
                var existingLedger = await _walletRepository.GetTransactionByReferenceAsync(
                    wallet.WalletId, "Credit", "TopUp", "PaymentTransaction", payment.PaymentId, cancellationToken);
                if (existingLedger != null)
                {
                    _logger.LogInformation("WalletTransaction already exists for PaymentTransaction {PaymentId}. Skipping credit.", payment.PaymentId);
                    await transaction.CommitAsync(cancellationToken);
                    return ApiResponse<object>.SuccessResponse(new { }, "Payment already settled.");
                }

                long balanceBefore = wallet.Balance;
                long balanceAfter = balanceBefore + payment.CreditAmount;

                wallet.Balance = balanceAfter;
                wallet.UpdatedAt = DateTime.UtcNow;
                await _walletRepository.UpdateWalletAsync(wallet, cancellationToken);

                // Create ledger entry
                var walletTx = new WalletTransaction
                {
                    WalletId = wallet.WalletId,
                    TransactionType = "Credit",
                    SourceType = "TopUp",
                    Amount = payment.CreditAmount,
                    BalanceBefore = balanceBefore,
                    BalanceAfter = balanceAfter,
                    ReferenceType = "PaymentTransaction",
                    ReferenceId = payment.PaymentId,
                    Description = $"Top up via PayOS - Order #{payment.ProviderOrderCode}",
                    CreatedAt = DateTime.UtcNow
                };

                await _walletRepository.AddTransactionAsync(walletTx, cancellationToken);

                await transaction.CommitAsync(cancellationToken);
                _logger.LogInformation("PaymentTransaction {PaymentId} successfully settled. Wallet {WalletId} credited {Credits} credits.",
                    payment.PaymentId, wallet.WalletId, payment.CreditAmount);

                return ApiResponse<object>.SuccessResponse(new { }, "Payment settled successfully.");
            }
            catch (Exception ex)
            {
                await transaction.RollbackAsync(cancellationToken);
                _logger.LogError(ex, "Error occurred during payment settlement for OrderCode {OrderCode}", verification.OrderCode);
                throw;
            }
        }
    }
}
