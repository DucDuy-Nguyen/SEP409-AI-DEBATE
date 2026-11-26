using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;
using PayOS.Models.Webhooks;
using SystemService.BLL.Common.Payment;
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
        private static long _lastOrderCode = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();

        private readonly SystemDbContext _context;
        private readonly IWalletRepository _walletRepository;
        private readonly ICreditPackageRepository _packageRepository;
        private readonly IPaymentRepository _paymentRepository;
        private readonly IPaymentGateway _paymentGateway;
        private readonly IConfiguration _configuration;
        private readonly ILogger<PaymentService> _logger;
        private readonly IRewardRepository? _rewardRepository;

        public PaymentService(
            SystemDbContext context,
            IWalletRepository walletRepository,
            ICreditPackageRepository packageRepository,
            IPaymentRepository paymentRepository,
            IPaymentGateway paymentGateway,
            IConfiguration configuration,
            ILogger<PaymentService> logger,
            IRewardRepository? rewardRepository = null)
        {
            _context = context;
            _walletRepository = walletRepository;
            _packageRepository = packageRepository;
            _paymentRepository = paymentRepository;
            _paymentGateway = paymentGateway;
            _configuration = configuration;
            _logger = logger;
            _rewardRepository = rewardRepository;
        }

        public async Task<ApiResponse<CustomTopUpQuoteResponse>> GetCustomTopUpQuoteAsync(
            long creditAmount,
            CancellationToken cancellationToken = default)
        {
            var (unitPriceVnd, minCredits, maxCredits) = await ResolveCustomTopUpPricingAsync(cancellationToken);

            var validationError = ValidateCustomTopUpAmount(creditAmount, unitPriceVnd, minCredits, maxCredits, out var totalAmountVnd);
            if (validationError != null)
            {
                return ApiResponse<CustomTopUpQuoteResponse>.FailureResponse(validationError);
            }

            return ApiResponse<CustomTopUpQuoteResponse>.SuccessResponse(new CustomTopUpQuoteResponse
            {
                CreditAmount = creditAmount,
                UnitPriceVnd = unitPriceVnd,
                TotalAmountVnd = totalAmountVnd,
                Currency = "VND",
                MinCredits = minCredits,
                MaxCredits = maxCredits
            }, "Tính báo giá mua Credit tự do thành công.");
        }

        public async Task<ApiResponse<PaymentLinkResponse>> CreateCustomTopUpPaymentAsync(
            int userId,
            CustomTopUpRequest request,
            CancellationToken cancellationToken = default)
        {
            if (request == null)
            {
                return ApiResponse<PaymentLinkResponse>.FailureResponse("Request body is required.");
            }

            var (unitPriceVnd, minCredits, maxCredits) = await ResolveCustomTopUpPricingAsync(cancellationToken);
            var validationError = ValidateCustomTopUpAmount(request.CreditAmount, unitPriceVnd, minCredits, maxCredits, out var totalAmountVnd);
            if (validationError != null)
            {
                return ApiResponse<PaymentLinkResponse>.FailureResponse(validationError);
            }

            if (!TryResolveRedirectUrls(request.FrontendOrigin, out var returnUrl, out var cancelUrl, out var originError))
            {
                return ApiResponse<PaymentLinkResponse>.FailureResponse(originError!);
            }

            var wallet = await _walletRepository.GetOrCreateWalletByUserIdAsync(userId, cancellationToken);
            long orderCode = GenerateUniqueOrderCode();

            var payment = new PaymentTransaction
            {
                UserId = userId,
                WalletId = wallet.WalletId,
                PackageId = null,
                Amount = totalAmountVnd,
                Currency = "VND",
                CreditAmount = request.CreditAmount,
                Provider = _paymentGateway.ProviderName,
                ProviderOrderCode = orderCode,
                Status = "Pending",
                CreatedAt = DateTime.UtcNow
            };

            await _paymentRepository.CreateAsync(payment, cancellationToken);

            var gatewayResult = await _paymentGateway.CreatePaymentLinkAsync(new PaymentLinkArgs
            {
                OrderCode = orderCode,
                Amount = totalAmountVnd,
                Description = $"TopUp {request.CreditAmount} CR",
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
                TopUpType = "Custom",
                UnitPriceVnd = unitPriceVnd,
                Status = payment.Status,
                CheckoutUrl = gatewayResult.CheckoutUrl,
                QrCode = gatewayResult.QrCode
            };

            if (!gatewayResult.Success)
            {
                _logger.LogWarning("Custom top-up payment link creation returned warning/error: {Error}", gatewayResult.ErrorMessage);
                return ApiResponse<PaymentLinkResponse>.SuccessResponse(response, $"Payment created pending gateway confirmation: {gatewayResult.ErrorMessage}");
            }

            return ApiResponse<PaymentLinkResponse>.SuccessResponse(response, "Custom credit payment link created successfully.");
        }

        public async Task<ApiResponse<PaymentLinkResponse>> CreateTopUpPaymentAsync(int userId, TopUpRequest request, CancellationToken cancellationToken = default)
        {
            var package = await _packageRepository.GetActiveByIdAsync(request.PackageId, cancellationToken);
            if (package == null)
            {
                return ApiResponse<PaymentLinkResponse>.FailureResponse("Credit package not found or is currently inactive.");
            }

            if (!TryResolveRedirectUrls(request.FrontendOrigin, out var returnUrl, out var cancelUrl, out var originError))
            {
                return ApiResponse<PaymentLinkResponse>.FailureResponse(originError!);
            }

            var wallet = await _walletRepository.GetOrCreateWalletByUserIdAsync(userId, cancellationToken);

            // Snapshot price and credit amounts
            decimal priceSnapshot = package.Price;
            long creditAmountSnapshot = package.CreditAmount + package.BonusCredit;

            // Generate unique OrderCode for PayOS (safe integer/long)
            long orderCode = GenerateUniqueOrderCode();

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
                TopUpType = "Package",
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

            bool isPackage = payment.PackageId.HasValue;
            var response = new PaymentStatusResponse
            {
                PaymentId = payment.PaymentId,
                TopUpType = isPackage ? "Package" : "Custom",
                PackageCode = isPackage ? payment.Package?.PackageCode : "CUSTOM",
                PackageName = isPackage ? payment.Package?.PackageName : "Nạp Credit tự do",
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
                if (verification.Amount != payment.Amount)
                {
                    _logger.LogWarning("PayOS webhook amount mismatch for OrderCode {OrderCode}: expected {Expected}, got {Actual}.",
                        verification.OrderCode, payment.Amount, verification.Amount);
                    await transaction.RollbackAsync(cancellationToken);
                    return ApiResponse<object>.FailureResponse("Webhook payment amount does not match expected payment amount.");
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
                    Description = payment.PackageId.HasValue
                        ? $"Top up via PayOS - Order #{payment.ProviderOrderCode}"
                        : $"Custom top up {payment.CreditAmount} credits via PayOS - Order #{payment.ProviderOrderCode}",
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

        private async Task<(decimal UnitPriceVnd, long MinCredits, long MaxCredits)> ResolveCustomTopUpPricingAsync(
            CancellationToken cancellationToken)
        {
            decimal unitPriceVnd = 0;

            if (_rewardRepository != null)
            {
                var dbRule = await _rewardRepository.GetActiveRuleByCodeAsync(
                    CreditRuleCodes.CustomTopUpUnitPriceVnd,
                    cancellationToken);
                if (dbRule != null && dbRule.CreditAmount > 0)
                {
                    unitPriceVnd = dbRule.CreditAmount;
                }
            }

            if (unitPriceVnd <= 0)
            {
                var configuredPrice = _configuration.GetValue<decimal?>("CustomTopUp:UnitPriceVnd");
                if (configuredPrice.HasValue && configuredPrice.Value > 0)
                {
                    unitPriceVnd = configuredPrice.Value;
                }
            }

            if (unitPriceVnd <= 0)
            {
                unitPriceVnd = CreditRuleCodes.DefaultCustomTopUpUnitPriceVnd;
            }

            var configuredMin = _configuration.GetValue<long?>("CustomTopUp:MinCredits");
            long minCredits = configuredMin.HasValue && configuredMin.Value > 0
                ? configuredMin.Value
                : CreditRuleCodes.DefaultCustomTopUpMinCredits;

            var configuredMax = _configuration.GetValue<long?>("CustomTopUp:MaxCredits");
            long maxCredits = configuredMax.HasValue && configuredMax.Value >= minCredits
                ? configuredMax.Value
                : Math.Max(minCredits, CreditRuleCodes.DefaultCustomTopUpMaxCredits);

            return (unitPriceVnd, minCredits, maxCredits);
        }

        private static string? ValidateCustomTopUpAmount(
            long creditAmount,
            decimal unitPriceVnd,
            long minCredits,
            long maxCredits,
            out decimal totalAmountVnd)
        {
            totalAmountVnd = 0;

            if (creditAmount <= 0)
            {
                return "CreditAmount must be a positive integer.";
            }

            if (creditAmount < minCredits)
            {
                return $"Minimum custom credit purchase is {minCredits} credits.";
            }

            if (creditAmount > maxCredits)
            {
                return $"Maximum custom credit purchase is {maxCredits} credits per transaction.";
            }

            totalAmountVnd = creditAmount * unitPriceVnd;
            if (totalAmountVnd <= 0 || totalAmountVnd > int.MaxValue || decimal.Truncate(totalAmountVnd) != totalAmountVnd)
            {
                return "Calculated payment amount is outside supported PayOS VND limits.";
            }

            return null;
        }

        private bool TryResolveRedirectUrls(
            string? requestedOrigin,
            out string returnUrl,
            out string cancelUrl,
            out string? errorMessage)
        {
            var allowedOrigins = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
            {
                "http://localhost:5173",
                "http://localhost:5174"
            };

            var configuredOrigin = _configuration["PayOS:FrontendOrigin"]?.Trim().TrimEnd('/');
            if (!string.IsNullOrWhiteSpace(configuredOrigin))
            {
                allowedOrigins.Add(configuredOrigin);
            }

            var frontendOrigin = requestedOrigin?.Trim().TrimEnd('/');
            if (string.IsNullOrWhiteSpace(frontendOrigin))
            {
                frontendOrigin = configuredOrigin;
            }

            if (string.IsNullOrWhiteSpace(frontendOrigin) || !allowedOrigins.Contains(frontendOrigin))
            {
                returnUrl = string.Empty;
                cancelUrl = string.Empty;
                errorMessage = "Invalid frontend origin.";
                return false;
            }

            returnUrl = $"{frontendOrigin}/payment/success";
            cancelUrl = $"{frontendOrigin}/payment/cancel";
            errorMessage = null;
            return true;
        }

        private static long GenerateUniqueOrderCode()
        {
            long now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            while (true)
            {
                long current = Interlocked.Read(ref _lastOrderCode);
                long next = now > current ? now : current + 1;
                if (Interlocked.CompareExchange(ref _lastOrderCode, next, current) == current)
                {
                    return next;
                }
            }
        }
    }
}
