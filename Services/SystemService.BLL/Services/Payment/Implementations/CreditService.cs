using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Data;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;
using SystemService.BLL.Common.Debate;
using SystemService.BLL.Common.Payment;
using SystemService.BLL.Common.Responses;
using SystemService.BLL.DTOs.AI;
using SystemService.BLL.DTOs.Debate;
using SystemService.BLL.DTOs.Payment;
using SystemService.BLL.Services.AI.Interfaces;
using SystemService.BLL.Services.Payment.Interfaces;
using SystemService.DAL.Context;
using SystemService.DAL.Entities.Debate;
using SystemService.DAL.Entities.Debate.Enums;
using SystemService.DAL.Entities.Payment;
using SystemService.DAL.Repositories.Debate.Interfaces;
using SystemService.DAL.Repositories.Payment.Interfaces;

namespace SystemService.BLL.Services.Payment.Implementations
{
    public class CreditService : ICreditService
    {
        private static readonly ConcurrentDictionary<string, SemaphoreSlim> _hintLocks = new();
        private static readonly ConcurrentDictionary<string, AiHintResponse> _completedHintCache = new();
        private static readonly TimeSpan AiHintTimeout = TimeSpan.FromSeconds(60);

        private readonly SystemDbContext _context;
        private readonly IRewardRepository _rewardRepository;
        private readonly IWalletRepository _walletRepository;
        private readonly IDebateRepository _debateRepository;
        private readonly IAiEvaluatorClient? _aiEvaluatorClient;
        private readonly ILogger<CreditService>? _logger;
        private readonly IConfiguration? _configuration;

        public CreditService(
            SystemDbContext context,
            IRewardRepository rewardRepository,
            IWalletRepository walletRepository,
            IDebateRepository debateRepository,
            IAiEvaluatorClient? aiEvaluatorClient = null,
            ILogger<CreditService>? logger = null,
            IConfiguration? configuration = null)
        {
            _context = context;
            _rewardRepository = rewardRepository;
            _walletRepository = walletRepository;
            _debateRepository = debateRepository;
            _aiEvaluatorClient = aiEvaluatorClient;
            _logger = logger;
            _configuration = configuration;
        }

        public async Task<long> GetRulePriceAsync(string ruleCode, CancellationToken cancellationToken = default)
        {
            if (string.IsNullOrWhiteSpace(ruleCode))
            {
                return 0;
            }

            if (string.Equals(ruleCode, CreditRuleCodes.P2pMatchPerUser, StringComparison.OrdinalIgnoreCase))
            {
                return 0;
            }

            var rule = await _rewardRepository.GetActiveRuleByCodeAsync(ruleCode, cancellationToken);
            if (rule != null && rule.CreditAmount > 0)
            {
                return rule.CreditAmount;
            }

            return CreditRuleCodes.GetDefaultPrice(ruleCode);
        }

        public async Task<ApiResponse<CreditPricesResponse>> GetPricesAsync(CancellationToken cancellationToken = default)
        {
            var aiPracticeRag = await GetRulePriceAsync(CreditRuleCodes.AiPracticeMatch, cancellationToken);
            var aiPracticeNoRag = await GetRulePriceAsync(CreditRuleCodes.AiPracticeNoRag, cancellationToken);
            var aiHint = await GetRulePriceAsync(CreditRuleCodes.AiHint, cancellationToken);
            var compSmall = await GetRulePriceAsync(CreditRuleCodes.CompetitionSmall, cancellationToken);
            var compMedium = await GetRulePriceAsync(CreditRuleCodes.CompetitionMedium, cancellationToken);
            var compLarge = await GetRulePriceAsync(CreditRuleCodes.CompetitionLarge, cancellationToken);

            var dbRules = await _rewardRepository.GetAllRulesAsync(cancellationToken);
            var ruleLookup = dbRules.ToDictionary(r => r.RuleCode, StringComparer.OrdinalIgnoreCase);

            var items = new List<CreditPriceRuleItemDto>
            {
                BuildRuleItem(ruleLookup, CreditRuleCodes.AiPracticeMatch, aiPracticeRag, "AI Practice có RAG (mỗi trận)", true, "Usage"),
                BuildRuleItem(ruleLookup, CreditRuleCodes.AiPracticeNoRag, aiPracticeNoRag, "AI Practice không RAG (mỗi trận)", true, "Usage"),
                BuildRuleItem(ruleLookup, CreditRuleCodes.AiHint, aiHint, "AI Hint / Hướng dẫn lập luận (mỗi lần)", true, "Usage"),
                BuildRuleItem(ruleLookup, CreditRuleCodes.CompetitionSmall, compSmall, "Tạo Competition nhỏ (tối đa 8 cá nhân hoặc 4 đội)", true, "Usage"),
                BuildRuleItem(ruleLookup, CreditRuleCodes.CompetitionMedium, compMedium, "Tạo Competition vừa (tối đa 16 cá nhân hoặc 8 đội)", true, "Usage"),
                BuildRuleItem(ruleLookup, CreditRuleCodes.CompetitionLarge, compLarge, "Tạo Competition lớn (tối đa 32 cá nhân hoặc 16 đội)", true, "Usage"),
                new()
                {
                    RuleCode = "P2P_1V1",
                    CreditAmount = 0,
                    Description = "Debate P2P 1v1 (Miễn phí)",
                    IsActive = true,
                    Category = "Free"
                },
                new()
                {
                    RuleCode = "P2P_2V2",
                    CreditAmount = 0,
                    Description = "Debate P2P 2v2 (Miễn phí)",
                    IsActive = true,
                    Category = "Free"
                },
                new()
                {
                    RuleCode = "COMPETITION_JOIN",
                    CreditAmount = 0,
                    Description = "Tham gia Competition (Miễn phí)",
                    IsActive = true,
                    Category = "Free"
                },
                new()
                {
                    RuleCode = "AI_EVALUATOR_P2P",
                    CreditAmount = 0,
                    Description = "AI Evaluator chấm P2P (Miễn phí)",
                    IsActive = true,
                    Category = "Free"
                }
            };

            foreach (var rewardCode in new[] { CreditRuleCodes.DailyLogin, CreditRuleCodes.FirstLogin })
            {
                if (ruleLookup.TryGetValue(rewardCode, out var rewardRule) && rewardRule.IsActive)
                {
                    items.Add(new CreditPriceRuleItemDto
                    {
                        RuleCode = rewardRule.RuleCode,
                        CreditAmount = rewardRule.CreditAmount,
                        Description = rewardRule.Description,
                        IsActive = rewardRule.IsActive,
                        Category = "Reward"
                    });
                }
            }

            var customUnitPrice = ResolveCustomTopUpUnitPrice(ruleLookup);
            var configuredMin = _configuration?.GetValue<long?>("CustomTopUp:MinCredits");
            long customMin = configuredMin.HasValue && configuredMin.Value > 0
                ? configuredMin.Value
                : CreditRuleCodes.DefaultCustomTopUpMinCredits;
            var configuredMax = _configuration?.GetValue<long?>("CustomTopUp:MaxCredits");
            long customMax = configuredMax.HasValue && configuredMax.Value >= customMin
                ? configuredMax.Value
                : Math.Max(customMin, CreditRuleCodes.DefaultCustomTopUpMaxCredits);

            items.Add(BuildRuleItem(
                ruleLookup,
                CreditRuleCodes.CustomTopUpUnitPriceVnd,
                (long)customUnitPrice,
                $"Đơn giá mua Credit tự do ({customUnitPrice:0} VNĐ / 1 Credit)",
                true,
                "TopUp"));

            var response = new CreditPricesResponse
            {
                AiPracticeRag = aiPracticeRag,
                AiPracticeNoRag = aiPracticeNoRag,
                IsAiPracticeNoRagSupported = true,
                AiHint = aiHint,
                CompetitionSmall = compSmall,
                CompetitionMedium = compMedium,
                CompetitionLarge = compLarge,
                P2p1v1 = 0,
                P2p2v2 = 0,
                CompetitionJoin = 0,
                AiEvaluatorP2p = 0,
                CustomTopUpUnitPriceVnd = customUnitPrice,
                CustomTopUpMinCredits = customMin,
                CustomTopUpMaxCredits = customMax,
                Rules = items
            };

            return ApiResponse<CreditPricesResponse>.SuccessResponse(response, "Lấy bảng giá Credit thành công.");
        }

        private decimal ResolveCustomTopUpUnitPrice(IReadOnlyDictionary<string, CreditRule> ruleLookup)
        {
            if (ruleLookup.TryGetValue(CreditRuleCodes.CustomTopUpUnitPriceVnd, out var dbRule)
                && dbRule.IsActive
                && dbRule.CreditAmount > 0)
            {
                return dbRule.CreditAmount;
            }

            var configured = _configuration?.GetValue<decimal?>("CustomTopUp:UnitPriceVnd");
            if (configured.HasValue && configured.Value > 0)
            {
                return configured.Value;
            }

            return CreditRuleCodes.DefaultCustomTopUpUnitPriceVnd;
        }

        public async Task<ApiResponse<CompetitionPriceQuoteResponse>> GetCompetitionPriceQuoteAsync(
            string competitionType,
            int? maxParticipants,
            int? maxTeams = null,
            CancellationToken cancellationToken = default)
        {
            if (!CreditRuleCodes.TryResolveCompetitionScale(
                    competitionType,
                    maxParticipants,
                    maxTeams,
                    out var scale,
                    out var ruleCode,
                    out var normalizedMaxParticipants,
                    out var normalizedMaxTeams,
                    out var errorMessage))
            {
                return ApiResponse<CompetitionPriceQuoteResponse>.FailureResponse(
                    errorMessage ?? "Invalid competition capacity.",
                    DebateErrorCodes.InvalidRequest);
            }

            var requiredCredits = await GetRulePriceAsync(ruleCode, cancellationToken);
            var normalizedType = competitionType.Trim().ToUpperInvariant() is "TEAM" or "2V2" ? "TEAM" : "INDIVIDUAL";

            return ApiResponse<CompetitionPriceQuoteResponse>.SuccessResponse(new CompetitionPriceQuoteResponse
            {
                CompetitionType = normalizedType,
                Scale = scale,
                RuleCode = ruleCode,
                MaxParticipants = normalizedMaxParticipants,
                MaxTeams = normalizedMaxTeams,
                RequiredCredits = requiredCredits
            }, "Tính phí tạo Competition thành công.");
        }

        public async Task<ApiResponse<AiHintResponse>> RequestArgumentHintAsync(
            int userId,
            AiHintRequest request,
            CancellationToken cancellationToken = default)
        {
            if (request == null || request.SessionId <= 0)
            {
                return ApiResponse<AiHintResponse>.FailureWithCode("SessionId is required.", DebateErrorCodes.InvalidRequest);
            }

            var requestId = request.RequestId?.Trim();
            if (string.IsNullOrWhiteSpace(requestId))
            {
                return ApiResponse<AiHintResponse>.FailureWithCode(
                    "RequestId (or X-Idempotency-Key) is required to prevent duplicate charges.",
                    DebateErrorCodes.InvalidRequest);
            }

            if (requestId.Length > 100)
            {
                return ApiResponse<AiHintResponse>.FailureWithCode(
                    "RequestId cannot exceed 100 characters.",
                    DebateErrorCodes.InvalidRequest);
            }

            if (_aiEvaluatorClient == null)
            {
                return ApiResponse<AiHintResponse>.FailureResponse("AI Evaluator service is not configured.");
            }

            var session = await _debateRepository.GetSessionWithDetailsAsync(request.SessionId, cancellationToken);
            if (session == null)
            {
                return ApiResponse<AiHintResponse>.FailureWithCode(
                    "Debate session not found.",
                    DebateErrorCodes.SessionNotFound);
            }

            if (session.Status == SessionStatus.Cancelled)
            {
                return ApiResponse<AiHintResponse>.FailureWithCode(
                    "Debate session has been cancelled.",
                    DebateErrorCodes.SessionNotInProgress);
            }

            if (session.Status == SessionStatus.Completed)
            {
                return ApiResponse<AiHintResponse>.FailureWithCode(
                    "Debate session has already completed.",
                    DebateErrorCodes.SessionNotInProgress);
            }

            if (session.Status == SessionStatus.Waiting)
            {
                return ApiResponse<AiHintResponse>.FailureWithCode(
                    "Debate session has not started yet.",
                    DebateErrorCodes.SessionNotInProgress);
            }

            var participant = session.Participants
                .FirstOrDefault(p => p.UserId == userId && p.ParticipantType == ParticipantType.USER);
            if (participant == null)
            {
                return ApiResponse<AiHintResponse>.FailureWithCode(
                    "You are not a participant in this debate session.",
                    DebateErrorCodes.NotParticipant);
            }

            var cacheKey = $"{userId}:{request.SessionId}:{requestId}";
            var semaphore = _hintLocks.GetOrAdd(cacheKey, _ => new SemaphoreSlim(1, 1));
            await semaphore.WaitAsync(cancellationToken);
            try
            {
                if (_completedHintCache.TryGetValue(cacheKey, out var cached))
                {
                    var latestWallet = await _walletRepository.GetOrCreateWalletByUserIdAsync(userId, cancellationToken);
                    var replayResponse = new AiHintResponse
                    {
                        SessionId = cached.SessionId,
                        ArgumentId = cached.ArgumentId,
                        RequestId = cached.RequestId,
                        CreditsCharged = cached.CreditsCharged,
                        RemainingBalance = latestWallet.Balance,
                        AlreadyProcessed = true,
                        Hint = cached.Hint,
                        Evaluation = cached.Evaluation
                    };
                    return ApiResponse<AiHintResponse>.SuccessResponse(replayResponse, "AI Hint retrieved (idempotent replay).");
                }

                // Resolve target argument or draft text BEFORE charging wallet.
                var target = ResolveHintTarget(session, participant, request);
                if (!target.Success)
                {
                    return ApiResponse<AiHintResponse>.FailureWithCode(target.ErrorMessage!, DebateErrorCodes.InvalidRequest);
                }

                var hintCost = await GetRulePriceAsync(CreditRuleCodes.AiHint, cancellationToken);
                var debitMarker = $"[HintReq:{requestId}]";
                var refundMarker = $"[HintRefund:{requestId}]";

                // Ensure wallet row exists before acquiring UPDLOCK transaction.
                await _walletRepository.GetOrCreateWalletByUserIdAsync(userId, cancellationToken);

                int walletId;
                long balanceAfterDebit;

                await using (var debitTx = await _context.Database.BeginTransactionAsync(IsolationLevel.ReadCommitted, cancellationToken))
                {
                    var wallet = await _walletRepository.GetByUserIdForUpdateAsync(userId, cancellationToken);
                    if (wallet == null)
                    {
                        await debitTx.RollbackAsync(cancellationToken);
                        return ApiResponse<AiHintResponse>.FailureResponse("Wallet not found.");
                    }

                    walletId = wallet.WalletId;

                    var existingDebit = await _walletRepository.GetTransactionByIdempotencyAsync(
                        wallet.WalletId, "AIHint", debitMarker, cancellationToken);
                    var existingRefund = await _walletRepository.GetTransactionByIdempotencyAsync(
                        wallet.WalletId, "AIHint", refundMarker, cancellationToken);

                    if (existingDebit != null && existingRefund == null)
                    {
                        // Check if this debit was orphaned due to server crash or timeout
                        var elapsed = DateTime.UtcNow - existingDebit.CreatedAt;
                        if (elapsed > TimeSpan.FromSeconds(30))
                        {
                            long restoredBalance = wallet.Balance + existingDebit.Amount;
                            wallet.Balance = restoredBalance;
                            wallet.UpdatedAt = DateTime.UtcNow;
                            await _walletRepository.UpdateWalletAsync(wallet, cancellationToken);

                            var autoRefund = new WalletTransaction
                            {
                                WalletId = wallet.WalletId,
                                TransactionType = "Credit",
                                SourceType = "Refund",
                                Amount = existingDebit.Amount,
                                BalanceBefore = wallet.Balance - existingDebit.Amount,
                                BalanceAfter = restoredBalance,
                                ReferenceType = "AIHint",
                                ReferenceId = session.DebateSessionId,
                                Description = $"Auto-refund orphaned AI Hint charge (crash/timeout recovery) user #{userId} session #{session.DebateSessionId} {refundMarker}",
                                CreatedAt = DateTime.UtcNow
                            };
                            await _walletRepository.AddTransactionAsync(autoRefund, cancellationToken);
                            await debitTx.CommitAsync(cancellationToken);

                            _logger?.LogWarning("Auto-refunded orphaned AI Hint debit for user {UserId}, session {SessionId}, requestId {RequestId} after crash/timeout.",
                                userId, session.DebateSessionId, requestId);

                            return ApiResponse<AiHintResponse>.FailureWithCode(
                                $"Yêu cầu trước đó bị gián đoạn do hệ thống quá tải hoặc khởi động lại. Đã tự động hoàn trả {existingDebit.Amount} Credit vào ví (Số dư: {restoredBalance}). Vui lòng thử lại.",
                                "ORPHANED_REQUEST_REFUNDED");
                        }

                        await debitTx.RollbackAsync(cancellationToken);
                        return ApiResponse<AiHintResponse>.FailureWithCode(
                            "A hint request with this RequestId is already being processed or has completed.",
                            "DUPLICATE_REQUEST");
                    }

                    if (wallet.Balance < hintCost)
                    {
                        await debitTx.RollbackAsync(cancellationToken);
                        return ApiResponse<AiHintResponse>.InsufficientCreditsResponse(hintCost, wallet.Balance);
                    }

                    long balanceBefore = wallet.Balance;
                    balanceAfterDebit = balanceBefore - hintCost;
                    wallet.Balance = balanceAfterDebit;
                    wallet.UpdatedAt = DateTime.UtcNow;

                    await _walletRepository.UpdateWalletAsync(wallet, cancellationToken);

                    var debitLedger = new WalletTransaction
                    {
                        WalletId = wallet.WalletId,
                        TransactionType = "Debit",
                        SourceType = "AiUsage",
                        Amount = hintCost,
                        BalanceBefore = balanceBefore,
                        BalanceAfter = balanceAfterDebit,
                        ReferenceType = "AIHint",
                        ReferenceId = session.DebateSessionId,
                        Description = $"AI Hint ({CreditRuleCodes.AiHint}) user #{userId} session #{session.DebateSessionId} {debitMarker}",
                        CreatedAt = DateTime.UtcNow
                    };
                    await _walletRepository.AddTransactionAsync(debitLedger, cancellationToken);

                    await debitTx.CommitAsync(cancellationToken);
                }

                // Call AI Evaluator outside the DB transaction so locks are not held across external HTTP calls.
                try
                {
                    using var timeoutCts = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
                    timeoutCts.CancelAfter(AiHintTimeout);

                    var evalReq = new EvaluateArgumentRequest(
                        Motion: target.Motion,
                        Side: target.SideStr,
                        Stage: target.StageStr,
                        ArgumentText: target.ArgumentText,
                        OpponentArgumentText: target.OpponentArgumentText,
                        DeliveryAnalytics: null);

                    var evalRes = await _aiEvaluatorClient.EvaluateArgumentAsync(evalReq, timeoutCts.Token);
                    if (evalRes == null || evalRes.Criteria == null || evalRes.Criteria.Count == 0)
                    {
                        throw new InvalidOperationException("AI Evaluator returned an invalid argument evaluation.");
                    }

                    var coachRes = await _aiEvaluatorClient.CoachArgumentAsync(
                        new ArgumentCoachingRequest(evalReq, evalRes), timeoutCts.Token);

                    if (coachRes == null || coachRes.FocusCriteria == null || coachRes.FocusCriteria.Count == 0 || coachRes.IdeaDevelopment == null)
                    {
                        throw new InvalidOperationException("AI Evaluator returned an empty coaching hint.");
                    }

                    var evaluationDto = new SingleArgumentEvaluationResponse
                    {
                        ArgumentId = target.ArgumentId ?? 0,
                        SessionId = session.DebateSessionId,
                        RoundNumber = target.RoundNumber,
                        Stage = target.StageStr,
                        Side = participant.Side.ToString(),
                        SpeakerName = participant.User?.FullName ?? $"User {userId}",
                        OverallScore = evalRes.OverallScore,
                        OverallReasoning = evalRes.OverallReasoning,
                        Criteria = evalRes.Criteria,
                        Strengths = evalRes.Strengths,
                        Weaknesses = evalRes.Weaknesses,
                        Suggestions = evalRes.Suggestions
                    };

                    var hintResponse = new AiHintResponse
                    {
                        SessionId = session.DebateSessionId,
                        ArgumentId = target.ArgumentId,
                        RequestId = requestId,
                        CreditsCharged = hintCost,
                        RemainingBalance = balanceAfterDebit,
                        AlreadyProcessed = false,
                        Hint = coachRes,
                        Evaluation = evaluationDto
                    };

                    _completedHintCache[cacheKey] = hintResponse;
                    return ApiResponse<AiHintResponse>.SuccessResponse(hintResponse, "Lấy gợi ý AI thành công.");
                }
                catch (Exception ex)
                {
                    _logger?.LogError(ex, "AI Hint failed for user {UserId}, session {SessionId}, requestId {RequestId}. Refunding {Amount} credits.",
                        userId, session.DebateSessionId, requestId, hintCost);

                    var refundedBalance = await RefundHintChargeAsync(userId, walletId, session.DebateSessionId, hintCost, refundMarker);

                    return ApiResponse<AiHintResponse>.FailureWithCode(
                        $"Không thể tạo gợi ý AI lúc này. Đã hoàn lại {hintCost} Credit vào ví (Số dư: {refundedBalance}).",
                        "AI_HINT_FAILED");
                }
            }
            finally
            {
                semaphore.Release();
            }
        }

        private async Task<long> RefundHintChargeAsync(
            int userId,
            int walletId,
            int sessionId,
            long amount,
            string refundMarker)
        {
            await using var refundTx = await _context.Database.BeginTransactionAsync(IsolationLevel.ReadCommitted, CancellationToken.None);
            try
            {
                var wallet = await _walletRepository.GetByIdForUpdateAsync(walletId, CancellationToken.None);
                if (wallet == null)
                {
                    await refundTx.RollbackAsync(CancellationToken.None);
                    return 0;
                }

                var existingRefund = await _walletRepository.GetTransactionByIdempotencyAsync(
                    wallet.WalletId, "AIHint", refundMarker, CancellationToken.None);
                if (existingRefund != null)
                {
                    await refundTx.CommitAsync(CancellationToken.None);
                    return wallet.Balance;
                }

                long balanceBefore = wallet.Balance;
                long balanceAfter = balanceBefore + amount;
                wallet.Balance = balanceAfter;
                wallet.UpdatedAt = DateTime.UtcNow;

                await _walletRepository.UpdateWalletAsync(wallet, CancellationToken.None);

                var refundLedger = new WalletTransaction
                {
                    WalletId = wallet.WalletId,
                    TransactionType = "Credit",
                    SourceType = "Refund",
                    Amount = amount,
                    BalanceBefore = balanceBefore,
                    BalanceAfter = balanceAfter,
                    ReferenceType = "AIHint",
                    ReferenceId = sessionId,
                    Description = $"Refund AI Hint ({CreditRuleCodes.AiHint}) user #{userId} session #{sessionId} {refundMarker}",
                    CreatedAt = DateTime.UtcNow
                };
                await _walletRepository.AddTransactionAsync(refundLedger, CancellationToken.None);

                await refundTx.CommitAsync(CancellationToken.None);
                return balanceAfter;
            }
            catch (Exception refundEx)
            {
                _logger?.LogCritical(refundEx, "Failed to refund AI Hint charge for user {UserId}, session {SessionId}, marker {Marker}",
                    userId, sessionId, refundMarker);
                await refundTx.RollbackAsync(CancellationToken.None);
                throw;
            }
        }

        private static CreditPriceRuleItemDto BuildRuleItem(
            Dictionary<string, CreditRule> lookup,
            string ruleCode,
            long activeAmount,
            string fallbackDescription,
            bool defaultActive,
            string category)
        {
            if (lookup.TryGetValue(ruleCode, out var rule))
            {
                return new CreditPriceRuleItemDto
                {
                    RuleCode = rule.RuleCode,
                    CreditAmount = activeAmount,
                    Description = string.IsNullOrWhiteSpace(rule.Description) ? fallbackDescription : rule.Description,
                    IsActive = rule.IsActive,
                    Category = category
                };
            }

            return new CreditPriceRuleItemDto
            {
                RuleCode = ruleCode,
                CreditAmount = activeAmount,
                Description = fallbackDescription,
                IsActive = defaultActive,
                Category = category
            };
        }

        private sealed record HintTargetResult(
            bool Success,
            string? ErrorMessage,
            int? ArgumentId,
            int RoundNumber,
            string Motion,
            string SideStr,
            string StageStr,
            string ArgumentText,
            string? OpponentArgumentText);

        private static HintTargetResult ResolveHintTarget(DebateSession session, DebateParticipant participant, AiHintRequest request)
        {
            var motion = session.Topic?.Description ?? session.Topic?.Title ?? "Debate motion";
            var sideStr = (participant.Side == DebateSide.PRO || participant.Side == DebateSide.Affirmative) ? "pro" : "con";

            DebateRound? targetRound = null;
            Argument? targetArgument = null;

            if (request.ArgumentId.HasValue)
            {
                var found = session.DebateRounds
                    .SelectMany(r => r.Arguments.Select(a => new { Round = r, Argument = a }))
                    .FirstOrDefault(x => x.Argument.ArgumentId == request.ArgumentId.Value);

                if (found == null)
                {
                    return new HintTargetResult(false, "Argument not found in this debate session.", null, 1, motion, sideStr, "opening", string.Empty, null);
                }

                if (found.Argument.ParticipantId != participant.ParticipantId)
                {
                    return new HintTargetResult(false, "You can only request AI Hint for your own argument.", null, 1, motion, sideStr, "opening", string.Empty, null);
                }

                targetRound = found.Round;
                targetArgument = found.Argument;
            }
            else if (!string.IsNullOrWhiteSpace(request.DraftText))
            {
                targetRound = request.RoundNumber.HasValue
                    ? session.DebateRounds.FirstOrDefault(r => r.RoundNumber == request.RoundNumber.Value)
                    : session.DebateRounds.OrderBy(r => r.RoundNumber).FirstOrDefault(r => !r.EndTime.HasValue)
                      ?? session.DebateRounds.OrderByDescending(r => r.RoundNumber).FirstOrDefault();
            }
            else
            {
                var latest = session.DebateRounds
                    .OrderByDescending(r => r.RoundNumber)
                    .SelectMany(r => r.Arguments
                        .Where(a => a.ParticipantId == participant.ParticipantId)
                        .OrderByDescending(a => a.SubmittedAt)
                        .ThenByDescending(a => a.ArgumentId)
                        .Select(a => new { Round = r, Argument = a }))
                    .FirstOrDefault();

                if (latest != null)
                {
                    targetRound = latest.Round;
                    targetArgument = latest.Argument;
                }
            }

            var argumentText = targetArgument?.Content ?? request.DraftText?.Trim() ?? string.Empty;
            if (string.IsNullOrWhiteSpace(argumentText))
            {
                return new HintTargetResult(
                    false,
                    "Vui lòng nhập nội dung lập luận (draftText) hoặc chọn một lập luận đã gửi (argumentId) để nhận gợi ý AI.",
                    null, 1, motion, sideStr, "opening", string.Empty, null);
            }

            int roundNumber = targetRound?.RoundNumber ?? 1;
            var roundType = targetRound?.RoundType ?? RoundType.OPENING;
            var stageStr = roundType switch
            {
                RoundType.OPENING => "opening",
                RoundType.REBUTTAL => "rebuttal",
                RoundType.CLOSING => "closing",
                _ => "rebuttal"
            };

            Argument? opponentArg = null;
            if (targetRound != null)
            {
                var cutoff = targetArgument?.SubmittedAt ?? DateTime.UtcNow;
                opponentArg = targetRound.Arguments
                    .Where(a => a.SubmittedAt < cutoff && a.Participant != null && a.Participant.Side != participant.Side)
                    .OrderByDescending(a => a.SubmittedAt)
                    .FirstOrDefault();
            }

            if (opponentArg == null)
            {
                var prevRound = session.DebateRounds
                    .Where(r => r.RoundNumber < roundNumber)
                    .OrderByDescending(r => r.RoundNumber)
                    .FirstOrDefault();
                opponentArg = prevRound?.Arguments
                    .Where(a => a.Participant != null && a.Participant.Side != participant.Side)
                    .OrderByDescending(a => a.SubmittedAt)
                    .FirstOrDefault();
            }

            return new HintTargetResult(
                true,
                null,
                targetArgument?.ArgumentId,
                roundNumber,
                motion,
                sideStr,
                stageStr,
                argumentText,
                opponentArg?.Content);
        }
    }
}
