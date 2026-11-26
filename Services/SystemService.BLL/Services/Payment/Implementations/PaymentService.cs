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
        private readonly ICreditRealtimeNotifier? _creditNotifier;

        public PaymentService(
            SystemDbContext context,
            IWalletRepository walletRepository,
            ICreditPackageRepository packageRepository,
            IPaymentRepository paymentRepository,
            IPaymentGateway paymentGateway,
            IConfiguration configuration,
            ILogger<PaymentService> logger,
            IRewardRepository? rewardRepository = null,
            ICreditRealtimeNotifier? creditNotifier = null)
        {
            _context = context;
            _walletRepository = walletRepository;
            _packageRepository = packageRepository;
            _paymentRepository = paymentRepository;
            _paymentGateway = paymentGateway;
            _configuration = configuration;
            _logger = logger;
            _rewardRepository = rewardRepository;
            _creditNotifier = creditNotifier;
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

            if (payment.Status == "Pending")
            {
                try
                {
                    var gatewayInfo = await _paymentGateway.GetPaymentLinkInformationAsync(payment.ProviderOrderCode, cancellationToken);
                    if (gatewayInfo.Success && !string.IsNullOrWhiteSpace(gatewayInfo.Status))
                    {
                        var upperStatus = gatewayInfo.Status.ToUpperInvariant();
                        if (upperStatus == "PAID")
                        {
                            payment = await SettlePaymentInternalAsync(payment, gatewayInfo.Reference, cancellationToken);
                        }
                        else if (upperStatus is "CANCELLED" or "CANCELED")
                        {
                            payment = await CancelPaymentInternalAsync(payment, cancellationToken);
                        }
                        else if (upperStatus == "EXPIRED")
                        {
                            payment = await ExpirePaymentInternalAsync(payment, cancellationToken);
                        }
                    }
                }
                catch (Exception ex)
                {
                    _logger.LogWarning(ex, "Failed to query PayOS payment link status for PaymentId {PaymentId}. Returning current DB status.", paymentId);
                }
            }

            var response = await MapToStatusResponseAsync(payment, cancellationToken);
            return ApiResponse<PaymentStatusResponse>.SuccessResponse(response);
        }

        public async Task<ApiResponse<PaymentStatusResponse>> GetPaymentStatusByOrderCodeAsync(int userId, long orderCode, CancellationToken cancellationToken = default)
        {
            var payment = await _paymentRepository.GetByProviderOrderCodeAsync(_paymentGateway.ProviderName, orderCode, cancellationToken);
            if (payment == null)
            {
                return ApiResponse<PaymentStatusResponse>.FailureResponse("Payment not found.");
            }

            if (payment.UserId != userId)
            {
                return ApiResponse<PaymentStatusResponse>.FailureResponse("Access denied.");
            }

            if (payment.Status == "Pending")
            {
                try
                {
                    var gatewayInfo = await _paymentGateway.GetPaymentLinkInformationAsync(orderCode, cancellationToken);
                    if (gatewayInfo.Success && !string.IsNullOrWhiteSpace(gatewayInfo.Status))
                    {
                        var upperStatus = gatewayInfo.Status.ToUpperInvariant();
                        if (upperStatus == "PAID")
                        {
                            payment = await SettlePaymentInternalAsync(payment, gatewayInfo.Reference, cancellationToken);
                        }
                        else if (upperStatus is "CANCELLED" or "CANCELED")
                        {
                            payment = await CancelPaymentInternalAsync(payment, cancellationToken);
                        }
                        else if (upperStatus == "EXPIRED")
                        {
                            payment = await ExpirePaymentInternalAsync(payment, cancellationToken);
                        }
                    }
                }
                catch (Exception ex)
                {
                    _logger.LogWarning(ex, "Failed to query PayOS payment link status for OrderCode {OrderCode}. Returning current DB status {Status}.",
                        orderCode, payment.Status);
                }
            }

            var response = await MapToStatusResponseAsync(payment, cancellationToken);
            return ApiResponse<PaymentStatusResponse>.SuccessResponse(response);
        }

        public async Task<ApiResponse<PaymentStatusResponse>> CancelPaymentByOrderCodeAsync(int userId, long orderCode, CancellationToken cancellationToken = default)
        {
            var payment = await _paymentRepository.GetByProviderOrderCodeAsync(_paymentGateway.ProviderName, orderCode, cancellationToken);
            if (payment == null)
            {
                return ApiResponse<PaymentStatusResponse>.FailureResponse("Payment not found.");
            }

            if (payment.UserId != userId)
            {
                return ApiResponse<PaymentStatusResponse>.FailureResponse("Access denied.");
            }

            if (payment.Status == "Paid")
            {
                return ApiResponse<PaymentStatusResponse>.FailureResponse("Cannot cancel a completed payment.");
            }

            if (payment.Status == "Pending")
            {
                payment = await CancelPaymentInternalAsync(payment, cancellationToken);
            }

            var response = await MapToStatusResponseAsync(payment, cancellationToken);
            return ApiResponse<PaymentStatusResponse>.SuccessResponse(response, "Payment cancelled successfully.");
        }

        public async Task<ApiResponse<object>> ProcessPayOSWebhookAsync(Webhook webhook, CancellationToken cancellationToken = default)
        {
            var verification = await _paymentGateway.VerifyWebhookAsync(webhook, cancellationToken);
            if (!verification.IsValid)
            {
                _logger.LogWarning("Invalid PayOS webhook signature: {Error}", verification.ErrorMessage);
                return ApiResponse<object>.FailureResponse($"Invalid webhook signature: {verification.ErrorMessage}");
            }

            var payment = await _paymentRepository.GetByProviderOrderCodeAsync(_paymentGateway.ProviderName, verification.OrderCode, cancellationToken);
            if (payment == null)
            {
                _logger.LogWarning("PaymentTransaction not found for ProviderOrderCode {OrderCode}", verification.OrderCode);
                return ApiResponse<object>.FailureResponse($"Payment transaction not found for order code {verification.OrderCode}.");
            }

            // Idempotency check: if already Paid, acknowledge without duplicate credit
            if (payment.Status == "Paid")
            {
                _logger.LogInformation("PaymentTransaction {PaymentId} is already Paid. Idempotent return.", payment.PaymentId);
                return ApiResponse<object>.SuccessResponse(new { }, "Payment already settled.");
            }

            // Do not credit cancelled/expired/failed transactions
            if (payment.Status is "Cancelled" or "Expired" or "Failed")
            {
                _logger.LogWarning("PaymentTransaction {PaymentId} has terminal status {Status}. Ignoring settlement.", payment.PaymentId, payment.Status);
                return ApiResponse<object>.FailureResponse($"Payment transaction is {payment.Status} and cannot be settled.");
            }

            // Verify PayOS payment result code ("00" means success)
            if (!string.Equals(verification.Code, "00", StringComparison.OrdinalIgnoreCase))
            {
                using var failTx = await _context.Database.BeginTransactionAsync(cancellationToken);
                var lockedPayment = await _paymentRepository.GetByProviderOrderCodeForUpdateAsync(_paymentGateway.ProviderName, verification.OrderCode, cancellationToken) ?? payment;
                lockedPayment.Status = "Failed";
                await _paymentRepository.UpdateAsync(lockedPayment, cancellationToken);
                await failTx.CommitAsync(cancellationToken);
                _logger.LogWarning("PayOS webhook for OrderCode {OrderCode} returned non-success code {Code}.", verification.OrderCode, verification.Code);
                return ApiResponse<object>.FailureResponse($"Payment was not successful (Code: {verification.Code}).");
            }

            // Server-side amount verification against snapshot
            if (verification.Amount != payment.Amount)
            {
                _logger.LogWarning("PayOS webhook amount mismatch for OrderCode {OrderCode}: expected {Expected}, got {Actual}.",
                    verification.OrderCode, payment.Amount, verification.Amount);
                return ApiResponse<object>.FailureResponse("Webhook payment amount does not match expected payment amount.");
            }

            await SettlePaymentInternalAsync(payment, verification.Reference, cancellationToken);
            return ApiResponse<object>.SuccessResponse(new { }, "Payment settled successfully.");
        }

        private async Task<PaymentTransaction> SettlePaymentInternalAsync(
            PaymentTransaction payment,
            string? providerTransactionId,
            CancellationToken cancellationToken)
        {
            using var transaction = await _context.Database.BeginTransactionAsync(cancellationToken);
            try
            {
                var lockedPayment = await _paymentRepository.GetByProviderOrderCodeForUpdateAsync(
                    payment.Provider, payment.ProviderOrderCode, cancellationToken) ?? payment;

                if (lockedPayment.Status == "Paid")
                {
                    _logger.LogInformation("PaymentTransaction {PaymentId} is already Paid. Idempotent return.", lockedPayment.PaymentId);
                    await transaction.CommitAsync(cancellationToken);
                    return lockedPayment;
                }

                lockedPayment.Status = "Paid";
                lockedPayment.PaidAt = DateTime.UtcNow;
                if (!string.IsNullOrWhiteSpace(providerTransactionId))
                {
                    lockedPayment.ProviderTransactionId = providerTransactionId;
                }
                await _paymentRepository.UpdateAsync(lockedPayment, cancellationToken);

                var wallet = await _walletRepository.GetByIdForUpdateAsync(lockedPayment.WalletId, cancellationToken);
                if (wallet == null)
                {
                    throw new InvalidOperationException($"Wallet {lockedPayment.WalletId} not found for payment {lockedPayment.PaymentId}.");
                }

                var existingLedger = await _walletRepository.GetTransactionByReferenceAsync(
                    wallet.WalletId, "Credit", "TopUp", "PaymentTransaction", lockedPayment.PaymentId, cancellationToken);

                if (existingLedger != null)
                {
                    _logger.LogInformation("WalletTransaction already exists for PaymentTransaction {PaymentId}. Skipping duplicate credit.", lockedPayment.PaymentId);
                    await transaction.CommitAsync(cancellationToken);
                    return lockedPayment;
                }

                long balanceBefore = wallet.Balance;
                long balanceAfter = balanceBefore + lockedPayment.CreditAmount;

                wallet.Balance = balanceAfter;
                wallet.UpdatedAt = DateTime.UtcNow;
                await _walletRepository.UpdateWalletAsync(wallet, cancellationToken);

                var walletTx = new WalletTransaction
                {
                    WalletId = wallet.WalletId,
                    TransactionType = "Credit",
                    SourceType = "TopUp",
                    Amount = lockedPayment.CreditAmount,
                    BalanceBefore = balanceBefore,
                    BalanceAfter = balanceAfter,
                    ReferenceType = "PaymentTransaction",
                    ReferenceId = lockedPayment.PaymentId,
                    Description = lockedPayment.PackageId.HasValue
                        ? $"Top up via PayOS - Order #{lockedPayment.ProviderOrderCode}"
                        : $"Custom top up {lockedPayment.CreditAmount} credits via PayOS - Order #{lockedPayment.ProviderOrderCode}",
                    CreatedAt = DateTime.UtcNow
                };

                await _walletRepository.AddTransactionAsync(walletTx, cancellationToken);
                await transaction.CommitAsync(cancellationToken);

                if (_creditNotifier != null)
                {
                    _ = _creditNotifier.NotifyCreditBalanceUpdatedAsync(
                        wallet.UserId, balanceAfter, balanceBefore, lockedPayment.CreditAmount, walletTx.WalletTransactionId, lockedPayment.PaymentId.ToString(), "PAYOS_TOPUP", CancellationToken.None);
                    _ = _creditNotifier.NotifyCreditTransactionCreatedAsync(
                        wallet.UserId,
                        new
                        {
                            transactionId = walletTx.WalletTransactionId,
                            walletId = wallet.WalletId,
                            amount = lockedPayment.CreditAmount,
                            type = "Credit",
                            sourceType = "TopUp",
                            balanceAfter = balanceAfter,
                            description = walletTx.Description,
                            createdAt = walletTx.CreatedAt
                        },
                        CancellationToken.None);
                }

                _logger.LogInformation("PaymentTransaction {PaymentId} successfully settled. Wallet {WalletId} credited {Credits} credits.",
                    lockedPayment.PaymentId, wallet.WalletId, lockedPayment.CreditAmount);

                return lockedPayment;
            }
            catch (Exception ex)
            {
                await transaction.RollbackAsync(cancellationToken);
                _logger.LogError(ex, "Error occurred during payment settlement for PaymentId {PaymentId}", payment.PaymentId);
                throw;
            }
        }

        private async Task<PaymentTransaction> CancelPaymentInternalAsync(
            PaymentTransaction payment,
            CancellationToken cancellationToken)
        {
            using var transaction = await _context.Database.BeginTransactionAsync(cancellationToken);
            try
            {
                var lockedPayment = await _paymentRepository.GetByProviderOrderCodeForUpdateAsync(
                    payment.Provider, payment.ProviderOrderCode, cancellationToken) ?? payment;

                if (lockedPayment.Status == "Paid")
                {
                    _logger.LogWarning("Attempted to cancel payment {PaymentId} which is already Paid. Keeping Paid status.", lockedPayment.PaymentId);
                    await transaction.CommitAsync(cancellationToken);
                    return lockedPayment;
                }

                if (lockedPayment.Status != "Cancelled")
                {
                    lockedPayment.Status = "Cancelled";
                    lockedPayment.CancelledAt = DateTime.UtcNow;
                    await _paymentRepository.UpdateAsync(lockedPayment, cancellationToken);
                    _logger.LogInformation("PaymentTransaction {PaymentId} (OrderCode {OrderCode}) marked as Cancelled.",
                        lockedPayment.PaymentId, lockedPayment.ProviderOrderCode);
                }

                await transaction.CommitAsync(cancellationToken);
                return lockedPayment;
            }
            catch (Exception ex)
            {
                await transaction.RollbackAsync(cancellationToken);
                _logger.LogError(ex, "Error occurred during payment cancellation for PaymentId {PaymentId}", payment.PaymentId);
                throw;
            }
        }

        private async Task<PaymentTransaction> ExpirePaymentInternalAsync(
            PaymentTransaction payment,
            CancellationToken cancellationToken)
        {
            using var transaction = await _context.Database.BeginTransactionAsync(cancellationToken);
            try
            {
                var lockedPayment = await _paymentRepository.GetByProviderOrderCodeForUpdateAsync(
                    payment.Provider, payment.ProviderOrderCode, cancellationToken) ?? payment;

                if (lockedPayment.Status == "Paid")
                {
                    await transaction.CommitAsync(cancellationToken);
                    return lockedPayment;
                }

                if (lockedPayment.Status != "Expired")
                {
                    lockedPayment.Status = "Expired";
                    lockedPayment.ExpiredAt = DateTime.UtcNow;
                    await _paymentRepository.UpdateAsync(lockedPayment, cancellationToken);
                }

                await transaction.CommitAsync(cancellationToken);
                return lockedPayment;
            }
            catch (Exception ex)
            {
                await transaction.RollbackAsync(cancellationToken);
                _logger.LogError(ex, "Error occurred while expiring PaymentId {PaymentId}", payment.PaymentId);
                throw;
            }
        }

        private async Task<PaymentStatusResponse> MapToStatusResponseAsync(
            PaymentTransaction payment,
            CancellationToken cancellationToken)
        {
            bool isPackage = payment.PackageId.HasValue;
            if (isPackage && payment.Package == null)
            {
                payment.Package = await _packageRepository.GetByIdAsync(payment.PackageId.Value, cancellationToken);
            }

            return new PaymentStatusResponse
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
