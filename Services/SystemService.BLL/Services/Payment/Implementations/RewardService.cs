using System;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;
using SystemService.BLL.Common.Responses;
using SystemService.BLL.DTOs.Payment;
using SystemService.BLL.Services.Payment.Interfaces;
using SystemService.DAL.Context;
using SystemService.DAL.Entities.Payment;
using SystemService.DAL.Repositories.Payment.Interfaces;

namespace SystemService.BLL.Services.Payment.Implementations
{
    public class RewardService : IRewardService
    {
        private readonly SystemDbContext _context;
        private readonly IRewardRepository _rewardRepository;
        private readonly IWalletRepository _walletRepository;
        private readonly ILogger<RewardService> _logger;

        public const string RuleDailyLogin = "DAILY_LOGIN";
        public const string RuleFirstLogin = "FIRST_LOGIN";

        public RewardService(
            SystemDbContext context,
            IRewardRepository rewardRepository,
            IWalletRepository walletRepository,
            ILogger<RewardService> logger)
        {
            _context = context;
            _rewardRepository = rewardRepository;
            _walletRepository = walletRepository;
            _logger = logger;
        }

        public async Task<ApiResponse<RewardStatusResponse>> GetRewardStatusAsync(int userId, CancellationToken cancellationToken = default)
        {
            var todayKey = DateTime.UtcNow.ToString("yyyy-MM-dd");

            var dailyRule = await _rewardRepository.GetActiveRuleByCodeAsync(RuleDailyLogin, cancellationToken);
            bool canClaimDaily = false;
            long dailyAmount = 0;
            if (dailyRule != null)
            {
                dailyAmount = dailyRule.CreditAmount;
                bool alreadyClaimedToday = await _rewardRepository.HasClaimedAsync(userId, dailyRule.RuleId, todayKey, cancellationToken);
                canClaimDaily = !alreadyClaimedToday;
            }

            var firstLoginRule = await _rewardRepository.GetActiveRuleByCodeAsync(RuleFirstLogin, cancellationToken);
            bool canClaimFirst = false;
            long firstAmount = 0;
            if (firstLoginRule != null)
            {
                firstAmount = firstLoginRule.CreditAmount;
                bool alreadyClaimedFirst = await _rewardRepository.HasClaimedAsync(userId, firstLoginRule.RuleId, "LIFETIME", cancellationToken);
                canClaimFirst = !alreadyClaimedFirst;
            }

            var response = new RewardStatusResponse
            {
                CanClaimDailyLogin = canClaimDaily,
                DailyLoginAmount = dailyAmount,
                CanClaimFirstLogin = canClaimFirst,
                FirstLoginAmount = firstAmount
            };

            return ApiResponse<RewardStatusResponse>.SuccessResponse(response);
        }

        public async Task<ApiResponse<RewardClaimResponse>> ClaimDailyLoginRewardAsync(int userId, CancellationToken cancellationToken = default)
        {
            var rule = await _rewardRepository.GetActiveRuleByCodeAsync(RuleDailyLogin, cancellationToken);
            if (rule == null)
            {
                return ApiResponse<RewardClaimResponse>.FailureResponse("Daily login reward is currently not active or not configured.");
            }

            var todayKey = DateTime.UtcNow.ToString("yyyy-MM-dd");
            var alreadyClaimed = await _rewardRepository.HasClaimedAsync(userId, rule.RuleId, todayKey, cancellationToken);
            if (alreadyClaimed)
            {
                return ApiResponse<RewardClaimResponse>.FailureResponse("Daily login reward has already been claimed for today.");
            }

            using var transaction = await _context.Database.BeginTransactionAsync(cancellationToken);
            try
            {
                // Lock wallet
                var wallet = await _walletRepository.GetByUserIdForUpdateAsync(userId, cancellationToken);
                if (wallet == null)
                {
                    wallet = await _walletRepository.GetOrCreateWalletByUserIdAsync(userId, cancellationToken);
                }

                // Check again to protect against race conditions
                bool duplicateCheck = await _rewardRepository.HasClaimedAsync(userId, rule.RuleId, todayKey, cancellationToken);
                if (duplicateCheck)
                {
                    await transaction.RollbackAsync(cancellationToken);
                    return ApiResponse<RewardClaimResponse>.FailureResponse("Daily login reward has already been claimed for today.");
                }

                var claim = new RewardClaim
                {
                    UserId = userId,
                    RuleId = rule.RuleId,
                    ClaimKey = todayKey,
                    ClaimedAt = DateTime.UtcNow
                };

                await _rewardRepository.CreateClaimAsync(claim, cancellationToken);

                long balanceBefore = wallet.Balance;
                long balanceAfter = balanceBefore + rule.CreditAmount;

                wallet.Balance = balanceAfter;
                wallet.UpdatedAt = DateTime.UtcNow;
                await _walletRepository.UpdateWalletAsync(wallet, cancellationToken);

                var walletTx = new WalletTransaction
                {
                    WalletId = wallet.WalletId,
                    TransactionType = "Credit",
                    SourceType = "Reward",
                    Amount = rule.CreditAmount,
                    BalanceBefore = balanceBefore,
                    BalanceAfter = balanceAfter,
                    ReferenceType = "RewardClaim",
                    ReferenceId = claim.RewardClaimId,
                    Description = $"Daily login reward ({todayKey})",
                    CreatedAt = DateTime.UtcNow
                };

                await _walletRepository.AddTransactionAsync(walletTx, cancellationToken);

                await transaction.CommitAsync(cancellationToken);

                var response = new RewardClaimResponse
                {
                    RewardClaimId = claim.RewardClaimId,
                    RuleCode = rule.RuleCode,
                    CreditAmount = rule.CreditAmount,
                    NewBalance = balanceAfter,
                    ClaimedAt = claim.ClaimedAt
                };

                return ApiResponse<RewardClaimResponse>.SuccessResponse(response, "Daily login reward claimed successfully.");
            }
            catch (DbUpdateException ex)
            {
                await transaction.RollbackAsync(cancellationToken);
                _logger.LogWarning(ex, "Concurrency or duplicate claim detected for user {UserId}", userId);
                return ApiResponse<RewardClaimResponse>.FailureResponse("Daily login reward has already been claimed for today.");
            }
            catch (Exception ex)
            {
                await transaction.RollbackAsync(cancellationToken);
                _logger.LogError(ex, "Failed to claim daily login reward for user {UserId}", userId);
                throw;
            }
        }

        public async Task<ApiResponse<RewardClaimResponse?>> ClaimFirstLoginRewardAsync(int userId, CancellationToken cancellationToken = default)
        {
            var rule = await _rewardRepository.GetActiveRuleByCodeAsync(RuleFirstLogin, cancellationToken);
            if (rule == null)
            {
                return ApiResponse<RewardClaimResponse?>.SuccessResponse(null, "First login reward is not configured.");
            }

            const string lifetimeKey = "LIFETIME";
            var alreadyClaimed = await _rewardRepository.HasClaimedAsync(userId, rule.RuleId, lifetimeKey, cancellationToken);
            if (alreadyClaimed)
            {
                return ApiResponse<RewardClaimResponse?>.SuccessResponse(null, "First login reward already claimed.");
            }

            using var transaction = await _context.Database.BeginTransactionAsync(cancellationToken);
            try
            {
                var wallet = await _walletRepository.GetByUserIdForUpdateAsync(userId, cancellationToken);
                if (wallet == null)
                {
                    wallet = await _walletRepository.GetOrCreateWalletByUserIdAsync(userId, cancellationToken);
                }

                bool duplicateCheck = await _rewardRepository.HasClaimedAsync(userId, rule.RuleId, lifetimeKey, cancellationToken);
                if (duplicateCheck)
                {
                    await transaction.RollbackAsync(cancellationToken);
                    return ApiResponse<RewardClaimResponse?>.SuccessResponse(null, "First login reward already claimed.");
                }

                var claim = new RewardClaim
                {
                    UserId = userId,
                    RuleId = rule.RuleId,
                    ClaimKey = lifetimeKey,
                    ClaimedAt = DateTime.UtcNow
                };

                await _rewardRepository.CreateClaimAsync(claim, cancellationToken);

                long balanceBefore = wallet.Balance;
                long balanceAfter = balanceBefore + rule.CreditAmount;

                wallet.Balance = balanceAfter;
                wallet.UpdatedAt = DateTime.UtcNow;
                await _walletRepository.UpdateWalletAsync(wallet, cancellationToken);

                var walletTx = new WalletTransaction
                {
                    WalletId = wallet.WalletId,
                    TransactionType = "Credit",
                    SourceType = "Reward",
                    Amount = rule.CreditAmount,
                    BalanceBefore = balanceBefore,
                    BalanceAfter = balanceAfter,
                    ReferenceType = "RewardClaim",
                    ReferenceId = claim.RewardClaimId,
                    Description = "First login welcome reward",
                    CreatedAt = DateTime.UtcNow
                };

                await _walletRepository.AddTransactionAsync(walletTx, cancellationToken);

                await transaction.CommitAsync(cancellationToken);

                var response = new RewardClaimResponse
                {
                    RewardClaimId = claim.RewardClaimId,
                    RuleCode = rule.RuleCode,
                    CreditAmount = rule.CreditAmount,
                    NewBalance = balanceAfter,
                    ClaimedAt = claim.ClaimedAt
                };

                return ApiResponse<RewardClaimResponse?>.SuccessResponse(response, "First login reward claimed successfully.");
            }
            catch (DbUpdateException ex)
            {
                await transaction.RollbackAsync(cancellationToken);
                _logger.LogWarning(ex, "First login reward duplicate caught for user {UserId}", userId);
                return ApiResponse<RewardClaimResponse?>.SuccessResponse(null, "First login reward already claimed.");
            }
            catch (Exception ex)
            {
                await transaction.RollbackAsync(cancellationToken);
                _logger.LogError(ex, "Failed to claim first login reward for user {UserId}", userId);
                throw;
            }
        }
    }
}
