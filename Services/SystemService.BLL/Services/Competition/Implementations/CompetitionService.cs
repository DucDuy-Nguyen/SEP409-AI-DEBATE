using System;
using System.Collections.Generic;
using System.Data;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.EntityFrameworkCore;
using SystemService.BLL.Common.Payment;
using SystemService.BLL.Common.Responses;
using SystemService.BLL.Services.Competition;
using SystemService.BLL.DTOs.Competition.Management;
using SystemService.BLL.Services.Competition.Interfaces;
using SystemService.BLL.Services.Payment.Interfaces;
using SystemService.DAL.Context;
using SystemService.DAL.Entities.Competition;
using SystemService.DAL.Entities.Payment;
using SystemService.DAL.Repositories.Competition.Interfaces;
using SystemService.DAL.Repositories.Identity.Interfaces;
using SystemService.DAL.Repositories.Payment.Interfaces;

namespace SystemService.BLL.Services.Competition.Implementations
{
    public class CompetitionService : ICompetitionService
    {
        private readonly ICompetitionRepository _competitionRepository;
        private readonly IDebateFormatRepository _debateFormatRepository;
        private readonly IUserRepository _userRepository;
        private readonly ICompetitionRegistrationRepository _registrationRepository;
        private readonly ICompetitionTeamRepository _teamRepository;
        private readonly IWalletRepository? _walletRepository;
        private readonly ICreditService? _creditService;
        private readonly SystemDbContext? _dbContext;
        private readonly ICreditRealtimeNotifier? _creditNotifier;

        public CompetitionService(
            ICompetitionRepository competitionRepository,
            IDebateFormatRepository debateFormatRepository,
            IUserRepository userRepository,
            ICompetitionRegistrationRepository registrationRepository,
            ICompetitionTeamRepository teamRepository,
            IWalletRepository? walletRepository = null,
            ICreditService? creditService = null,
            SystemDbContext? dbContext = null,
            ICreditRealtimeNotifier? creditNotifier = null)
        {
            _competitionRepository = competitionRepository;
            _debateFormatRepository = debateFormatRepository;
            _userRepository = userRepository;
            _registrationRepository = registrationRepository;
            _teamRepository = teamRepository;
            _walletRepository = walletRepository;
            _creditService = creditService;
            _dbContext = dbContext;
            _creditNotifier = creditNotifier;
        }

        public async Task<ApiResponse<CompetitionResponse>> CreateAsync(int createdByUserId, CreateCompetitionRequest request, CancellationToken cancellationToken = default)
        {
            var creator = await _userRepository.GetUserWithRolesAsync(createdByUserId, cancellationToken);
            if (creator == null)
            {
                return ApiResponse<CompetitionResponse>.FailureResponse("User not found.");
            }

            if (!creator.IsActive)
            {
                return ApiResponse<CompetitionResponse>.FailureResponse("User account is inactive.", CompetitionErrorCodes.Forbidden);
            }

            if (string.IsNullOrWhiteSpace(request.Title))
            {
                return ApiResponse<CompetitionResponse>.FailureResponse("Title is required.");
            }

            var trimmedTitle = request.Title.Trim();
            if (trimmedTitle.Length > 200)
            {
                return ApiResponse<CompetitionResponse>.FailureResponse("Title must not exceed 200 characters.");
            }

            var type = request.CompetitionType?.ToUpperInvariant();
            if (type != "INDIVIDUAL" && type != "TEAM")
            {
                return ApiResponse<CompetitionResponse>.FailureResponse("CompetitionType must be either INDIVIDUAL or TEAM.");
            }

            if (request.FormatId.HasValue)
            {
                if (request.FormatId.Value <= 0)
                {
                    return ApiResponse<CompetitionResponse>.FailureResponse("FormatId must be greater than 0 or null.");
                }

                var formatExists = await _debateFormatRepository.ExistsAsync(request.FormatId.Value, cancellationToken);
                if (!formatExists)
                {
                    return ApiResponse<CompetitionResponse>.FailureResponse($"Debate format with FormatId {request.FormatId.Value} does not exist.");
                }
            }

            if (!CreditRuleCodes.TryResolveCompetitionScale(
                    type,
                    request.MaxParticipants,
                    maxTeams: null,
                    out var scale,
                    out var ruleCode,
                    out var normalizedMaxParticipants,
                    out _,
                    out var scaleError))
            {
                return ApiResponse<CompetitionResponse>.FailureResponse(scaleError ?? "Invalid competition capacity.");
            }

            if (request.RegistrationEnd <= request.RegistrationStart)
            {
                return ApiResponse<CompetitionResponse>.FailureResponse("RegistrationEnd must be after RegistrationStart.");
            }

            if (request.StartDate < request.RegistrationEnd)
            {
                return ApiResponse<CompetitionResponse>.FailureResponse("StartDate must be on or after RegistrationEnd.");
            }

            if (request.EndDate.HasValue && request.EndDate.Value < request.StartDate)
            {
                return ApiResponse<CompetitionResponse>.FailureResponse("EndDate must be on or after StartDate.");
            }

            var requestId = request.RequestId?.Trim();
            long requiredCredits = _creditService != null
                ? await _creditService.GetRulePriceAsync(ruleCode, cancellationToken)
                : CreditRuleCodes.GetDefaultPrice(ruleCode);

            if (_dbContext != null && _walletRepository != null)
            {
                await _walletRepository.GetOrCreateWalletByUserIdAsync(createdByUserId, cancellationToken);

                await using var transaction = await _dbContext.Database.BeginTransactionAsync(IsolationLevel.ReadCommitted, cancellationToken);
                try
                {
                    var wallet = await _walletRepository.GetByUserIdForUpdateAsync(createdByUserId, cancellationToken);
                    if (wallet == null)
                    {
                        await transaction.RollbackAsync(cancellationToken);
                        return ApiResponse<CompetitionResponse>.FailureResponse("Wallet not found.");
                    }

                    // Idempotency check on retry using RequestId
                    if (!string.IsNullOrWhiteSpace(requestId))
                    {
                        var marker = $"[CompReq:{requestId}]";
                        var existingTx = await _walletRepository.GetTransactionByIdempotencyAsync(
                            wallet.WalletId, "Competition", marker, cancellationToken);
                        if (existingTx?.ReferenceId != null)
                        {
                            var existingComp = await _competitionRepository.GetByIdAsync((int)existingTx.ReferenceId.Value, cancellationToken);
                            if (existingComp != null)
                            {
                                await transaction.CommitAsync(cancellationToken);
                                var replayResp = MapToResponse(existingComp, scale, existingTx.Amount, wallet.Balance);
                                return ApiResponse<CompetitionResponse>.SuccessResponse(replayResp, "Competition already created (idempotent replay).");
                            }
                        }
                    }

                    // Duplicate submit protection without RequestId within short retry window
                    var duplicateWindowStart = DateTime.UtcNow.AddSeconds(-30);
                    var recentDuplicate = await _dbContext.Competitions
                        .AsNoTracking()
                        .FirstOrDefaultAsync(c =>
                            c.CreatedBy == createdByUserId
                            && c.Title == trimmedTitle
                            && c.CompetitionType == type
                            && c.MaxParticipants == normalizedMaxParticipants
                            && c.RegistrationStart == request.RegistrationStart
                            && c.RegistrationEnd == request.RegistrationEnd
                            && c.StartDate == request.StartDate
                            && c.CreatedAt >= duplicateWindowStart,
                            cancellationToken);

                    if (recentDuplicate != null && string.IsNullOrWhiteSpace(requestId))
                    {
                        await transaction.CommitAsync(cancellationToken);
                        var dupResp = MapToResponse(recentDuplicate, scale, requiredCredits, wallet.Balance);
                        return ApiResponse<CompetitionResponse>.SuccessResponse(dupResp, "Competition already created.");
                    }

                    if (wallet.Balance < requiredCredits)
                    {
                        await transaction.RollbackAsync(cancellationToken);
                        return ApiResponse<CompetitionResponse>.InsufficientCreditsResponse(requiredCredits, wallet.Balance);
                    }

                    var competition = new SystemService.DAL.Entities.Competition.Competition
                    {
                        Title = trimmedTitle,
                        Description = request.Description,
                        CreatedBy = createdByUserId,
                        CompetitionType = type,
                        FormatId = request.FormatId,
                        MaxParticipants = normalizedMaxParticipants,
                        RegistrationStart = request.RegistrationStart,
                        RegistrationEnd = request.RegistrationEnd,
                        StartDate = request.StartDate,
                        EndDate = request.EndDate,
                        Status = "Draft",
                        IsPublic = request.IsPublic,
                        CreatedAt = DateTime.UtcNow
                    };

                    await _dbContext.Competitions.AddAsync(competition, cancellationToken);
                    await _dbContext.SaveChangesAsync(cancellationToken);

                    var judge = new CompetitionJudge
                    {
                        CompetitionId = competition.CompetitionId,
                        UserId = createdByUserId,
                        AssignedAt = DateTime.UtcNow
                    };
                    await _dbContext.CompetitionJudges.AddAsync(judge, cancellationToken);
                    await _dbContext.SaveChangesAsync(cancellationToken);

                    long balanceBefore = wallet.Balance;
                    long balanceAfter = balanceBefore - requiredCredits;
                    wallet.Balance = balanceAfter;
                    wallet.UpdatedAt = DateTime.UtcNow;
                    await _walletRepository.UpdateWalletAsync(wallet, cancellationToken);

                    var markerSuffix = !string.IsNullOrWhiteSpace(requestId) ? $" [CompReq:{requestId}]" : string.Empty;
                    var walletTx = new WalletTransaction
                    {
                        WalletId = wallet.WalletId,
                        TransactionType = "Debit",
                        SourceType = "AiUsage",
                        Amount = requiredCredits,
                        BalanceBefore = balanceBefore,
                        BalanceAfter = balanceAfter,
                        ReferenceType = "Competition",
                        ReferenceId = competition.CompetitionId,
                        Description = $"Create {scale} {type} competition #{competition.CompetitionId} ({ruleCode}) user #{createdByUserId}{markerSuffix}",
                        CreatedAt = DateTime.UtcNow
                    };
                    await _walletRepository.AddTransactionAsync(walletTx, cancellationToken);

                    await transaction.CommitAsync(cancellationToken);

                    if (_creditNotifier != null)
                    {
                        _ = _creditNotifier.NotifyCreditBalanceUpdatedAsync(
                            createdByUserId, balanceAfter, balanceBefore, -requiredCredits, walletTx.WalletTransactionId, competition.CompetitionId.ToString(), "CREATE_COMPETITION", CancellationToken.None);
                        _ = _creditNotifier.NotifyCreditTransactionCreatedAsync(
                            createdByUserId,
                            new
                            {
                                transactionId = walletTx.WalletTransactionId,
                                walletId = wallet.WalletId,
                                amount = requiredCredits,
                                type = "Debit",
                                sourceType = "AiUsage",
                                balanceAfter = balanceAfter,
                                description = walletTx.Description,
                                createdAt = walletTx.CreatedAt
                            },
                            CancellationToken.None);
                    }

                    var response = MapToResponse(competition, scale, requiredCredits, balanceAfter);
                    return ApiResponse<CompetitionResponse>.SuccessResponse(response, "Competition created successfully.");
                }
                catch
                {
                    await transaction.RollbackAsync(cancellationToken);
                    throw;
                }
            }

            var fallbackCompetition = new SystemService.DAL.Entities.Competition.Competition
            {
                Title = trimmedTitle,
                Description = request.Description,
                CreatedBy = createdByUserId,
                CompetitionType = type,
                FormatId = request.FormatId,
                MaxParticipants = normalizedMaxParticipants,
                RegistrationStart = request.RegistrationStart,
                RegistrationEnd = request.RegistrationEnd,
                StartDate = request.StartDate,
                EndDate = request.EndDate,
                Status = "Draft",
                IsPublic = request.IsPublic,
                CreatedAt = DateTime.UtcNow
            };

            var fallbackJudge = new CompetitionJudge
            {
                UserId = createdByUserId,
                AssignedAt = DateTime.UtcNow
            };

            await _competitionRepository.CreateWithJudgeAsync(fallbackCompetition, fallbackJudge, cancellationToken);

            var fallbackResponse = MapToResponse(fallbackCompetition, scale, 0, null);
            return ApiResponse<CompetitionResponse>.SuccessResponse(fallbackResponse, "Competition created successfully.");
        }

        public async Task<ApiResponse<CompetitionResponse>> PatchAsync(int competitionId, int currentUserId, PatchCompetitionRequest request, CancellationToken cancellationToken = default)
        {
            var competition = await _competitionRepository.GetByIdAsync(competitionId, cancellationToken);
            if (competition == null)
            {
                return ApiResponse<CompetitionResponse>.FailureResponse("Competition not found.", CompetitionErrorCodes.NotFound);
            }

            if (competition.CreatedBy != currentUserId)
            {
                return ApiResponse<CompetitionResponse>.FailureResponse("Only the competition creator may manage it.", CompetitionErrorCodes.Forbidden);
            }

            if (competition.Status == "Completed" || competition.Status == "Cancelled")
            {
                return ApiResponse<CompetitionResponse>.FailureResponse("Completed or cancelled competitions cannot be changed.", CompetitionErrorCodes.Conflict);
            }

            var existingRounds = await _competitionRepository.GetRoundsWithMatchesAsync(competitionId, cancellationToken);

            if (!request.HasAnyProperty)
            {
                return ApiResponse<CompetitionResponse>.FailureResponse("At least one field must be provided for update.");
            }

            if (request.HasTitle)
            {
                if (string.IsNullOrWhiteSpace(request.Title))
                {
                    return ApiResponse<CompetitionResponse>.FailureResponse("Title cannot be empty or whitespace.");
                }
                var trimmedTitle = request.Title.Trim();
                if (trimmedTitle.Length > 200)
                {
                    return ApiResponse<CompetitionResponse>.FailureResponse("Title must not exceed 200 characters.");
                }
            }

            if (request.HasFormatId && request.FormatId.HasValue)
            {
                if (request.FormatId.Value <= 0)
                {
                    return ApiResponse<CompetitionResponse>.FailureResponse("FormatId must be greater than 0 or null.");
                }

                var formatExists = await _debateFormatRepository.ExistsAsync(request.FormatId.Value, cancellationToken);
                if (!formatExists)
                {
                    return ApiResponse<CompetitionResponse>.FailureResponse($"Debate format with FormatId {request.FormatId.Value} does not exist.");
                }
            }

            string? upgradedScale = null;
            string? upgradedRuleCode = null;
            long upgradeDelta = 0;

            if (request.HasMaxParticipants)
            {
                if (!CreditRuleCodes.TryResolveCompetitionScale(
                        competition.CompetitionType,
                        request.MaxParticipants,
                        maxTeams: null,
                        out var newScale,
                        out var newRuleCode,
                        out var normalizedNewCapacity,
                        out _,
                        out var scaleError))
                {
                    return ApiResponse<CompetitionResponse>.FailureResponse(scaleError ?? "Invalid MaxParticipants.");
                }

                upgradedScale = newScale;
                upgradedRuleCode = newRuleCode;
                request.MaxParticipants = normalizedNewCapacity;
            }

            if (existingRounds.Count > 0 && (request.HasFormatId || request.HasMaxParticipants || request.HasRegistrationStart || request.HasRegistrationEnd))
            {
                return ApiResponse<CompetitionResponse>.FailureResponse("Bracket-dependent settings cannot change after bracket creation.", CompetitionErrorCodes.Conflict);
            }

            if (request.HasRegistrationStart && !request.RegistrationStart.HasValue)
            {
                return ApiResponse<CompetitionResponse>.FailureResponse("RegistrationStart cannot be null.");
            }

            if (request.HasRegistrationEnd && !request.RegistrationEnd.HasValue)
            {
                return ApiResponse<CompetitionResponse>.FailureResponse("RegistrationEnd cannot be null.");
            }

            if (request.HasStartDate && !request.StartDate.HasValue)
            {
                return ApiResponse<CompetitionResponse>.FailureResponse("StartDate cannot be null.");
            }

            if (request.HasIsPublic && !request.IsPublic.HasValue)
            {
                return ApiResponse<CompetitionResponse>.FailureResponse("IsPublic cannot be null.");
            }

            var effectiveRegistrationStart = request.HasRegistrationStart && request.RegistrationStart.HasValue
                ? request.RegistrationStart.Value
                : competition.RegistrationStart;

            var effectiveRegistrationEnd = request.HasRegistrationEnd && request.RegistrationEnd.HasValue
                ? request.RegistrationEnd.Value
                : competition.RegistrationEnd;

            var effectiveStartDate = request.HasStartDate && request.StartDate.HasValue
                ? request.StartDate.Value
                : competition.StartDate;

            var effectiveEndDate = request.HasEndDate
                ? request.EndDate
                : competition.EndDate;

            if (effectiveRegistrationEnd <= effectiveRegistrationStart)
            {
                return ApiResponse<CompetitionResponse>.FailureResponse("RegistrationEnd must be after RegistrationStart.");
            }

            if (effectiveStartDate < effectiveRegistrationEnd)
            {
                return ApiResponse<CompetitionResponse>.FailureResponse("StartDate must be on or after RegistrationEnd.");
            }

            if (effectiveEndDate.HasValue && effectiveEndDate.Value < effectiveStartDate)
            {
                return ApiResponse<CompetitionResponse>.FailureResponse("EndDate must be on or after StartDate.");
            }

            if (request.HasMaxParticipants && upgradedRuleCode != null && _dbContext != null && _walletRepository != null)
            {
                long newFee = _creditService != null
                    ? await _creditService.GetRulePriceAsync(upgradedRuleCode, cancellationToken)
                    : CreditRuleCodes.GetDefaultPrice(upgradedRuleCode);

                long oldScaleFee = 0;
                if (competition.MaxParticipants.HasValue
                    && CreditRuleCodes.TryResolveCompetitionScale(
                        competition.CompetitionType,
                        competition.MaxParticipants,
                        maxTeams: null,
                        out _,
                        out var oldRuleCode,
                        out _,
                        out _,
                        out _))
                {
                    oldScaleFee = _creditService != null
                        ? await _creditService.GetRulePriceAsync(oldRuleCode, cancellationToken)
                        : CreditRuleCodes.GetDefaultPrice(oldRuleCode);
                }

                await _walletRepository.GetOrCreateWalletByUserIdAsync(currentUserId, cancellationToken);

                await using var tx = await _dbContext.Database.BeginTransactionAsync(IsolationLevel.ReadCommitted, cancellationToken);
                try
                {
                    var wallet = await _walletRepository.GetByUserIdForUpdateAsync(currentUserId, cancellationToken);
                    if (wallet == null)
                    {
                        await tx.RollbackAsync(cancellationToken);
                        return ApiResponse<CompetitionResponse>.FailureResponse("Wallet not found.");
                    }

                    var pastTxs = await _walletRepository.GetTransactionsByReferenceAsync(
                        wallet.WalletId, "Competition", competition.CompetitionId, cancellationToken);
                    long paidFromLedger = pastTxs
                        .Where(t => t.TransactionType == "Debit" && t.SourceType == "AiUsage")
                        .Sum(t => t.Amount);

                    long coveredFee = Math.Max(paidFromLedger, oldScaleFee);
                    upgradeDelta = newFee > coveredFee ? newFee - coveredFee : 0;

                    WalletTransaction? upgradeTx = null;
                    long balanceBefore = 0;
                    long balanceAfter = 0;

                    if (upgradeDelta > 0)
                    {
                        if (wallet.Balance < upgradeDelta)
                        {
                            await tx.RollbackAsync(cancellationToken);
                            return ApiResponse<CompetitionResponse>.InsufficientCreditsResponse(upgradeDelta, wallet.Balance);
                        }

                        balanceBefore = wallet.Balance;
                        balanceAfter = balanceBefore - upgradeDelta;
                        wallet.Balance = balanceAfter;
                        wallet.UpdatedAt = DateTime.UtcNow;
                        await _walletRepository.UpdateWalletAsync(wallet, cancellationToken);

                        upgradeTx = new WalletTransaction
                        {
                            WalletId = wallet.WalletId,
                            TransactionType = "Debit",
                            SourceType = "AiUsage",
                            Amount = upgradeDelta,
                            BalanceBefore = balanceBefore,
                            BalanceAfter = balanceAfter,
                            ReferenceType = "Competition",
                            ReferenceId = competition.CompetitionId,
                            Description = $"Upgrade competition #{competition.CompetitionId} scale to {upgradedScale} ({upgradedRuleCode}) user #{currentUserId}",
                            CreatedAt = DateTime.UtcNow
                        };
                        await _walletRepository.AddTransactionAsync(upgradeTx, cancellationToken);
                    }

                    ApplyPatchFields(competition, request);
                    await _competitionRepository.UpdateAsync(competition, cancellationToken);
                    await tx.CommitAsync(cancellationToken);

                    if (upgradeDelta > 0 && upgradeTx != null && _creditNotifier != null)
                    {
                        _ = _creditNotifier.NotifyCreditBalanceUpdatedAsync(
                            currentUserId, balanceAfter, balanceBefore, -upgradeDelta, upgradeTx.WalletTransactionId, competition.CompetitionId.ToString(), "UPGRADE_COMPETITION", CancellationToken.None);
                        _ = _creditNotifier.NotifyCreditTransactionCreatedAsync(
                            currentUserId,
                            new
                            {
                                transactionId = upgradeTx.WalletTransactionId,
                                walletId = wallet.WalletId,
                                amount = upgradeDelta,
                                type = "Debit",
                                sourceType = "AiUsage",
                                balanceAfter = balanceAfter,
                                description = upgradeTx.Description,
                                createdAt = upgradeTx.CreatedAt
                            },
                            CancellationToken.None);
                    }

                    return ApiResponse<CompetitionResponse>.SuccessResponse(
                        MapToResponse(competition, upgradedScale, upgradeDelta, wallet.Balance),
                        "Competition updated successfully.");
                }
                catch
                {
                    await tx.RollbackAsync(cancellationToken);
                    throw;
                }
            }

            ApplyPatchFields(competition, request);
            await _competitionRepository.UpdateAsync(competition, cancellationToken);

            var response = MapToResponse(competition, upgradedScale, 0, null);
            return ApiResponse<CompetitionResponse>.SuccessResponse(response, "Competition updated successfully.");
        }

        private static void ApplyPatchFields(SystemService.DAL.Entities.Competition.Competition competition, PatchCompetitionRequest request)
        {
            if (request.HasTitle)
            {
                competition.Title = request.Title!.Trim();
            }

            if (request.HasDescription)
            {
                competition.Description = request.Description;
            }

            if (request.HasFormatId)
            {
                competition.FormatId = request.FormatId;
            }

            if (request.HasMaxParticipants)
            {
                competition.MaxParticipants = request.MaxParticipants;
            }

            if (request.HasRegistrationStart)
            {
                competition.RegistrationStart = request.RegistrationStart!.Value;
            }

            if (request.HasRegistrationEnd)
            {
                competition.RegistrationEnd = request.RegistrationEnd!.Value;
            }

            if (request.HasStartDate)
            {
                competition.StartDate = request.StartDate!.Value;
            }

            if (request.HasEndDate)
            {
                competition.EndDate = request.EndDate;
            }

            if (request.HasIsPublic)
            {
                competition.IsPublic = request.IsPublic!.Value;
            }

            competition.UpdatedAt = DateTime.UtcNow;
        }

        public async Task<ApiResponse<CompetitionDetailResponse>> GetByIdAsync(int competitionId, CancellationToken cancellationToken = default)
        {
            var competition = await _competitionRepository.GetDetailByIdAsync(competitionId, cancellationToken);
            if (competition == null)
            {
                return ApiResponse<CompetitionDetailResponse>.FailureResponse("Competition not found.");
            }

            var response = new CompetitionDetailResponse
            {
                CompetitionId = competition.CompetitionId,
                Title = competition.Title,
                Description = competition.Description,
                CreatedBy = competition.CreatedBy,
                CreatedByName = competition.Creator?.FullName ?? string.Empty,
                CompetitionType = competition.CompetitionType,
                FormatId = competition.FormatId,
                FormatName = null, // Format name mapped if loaded
                MaxParticipants = competition.MaxParticipants,
                RegistrationStart = competition.RegistrationStart,
                RegistrationEnd = competition.RegistrationEnd,
                StartDate = competition.StartDate,
                EndDate = competition.EndDate,
                Status = competition.Status,
                IsPublic = competition.IsPublic,
                CreatedAt = competition.CreatedAt,
                UpdatedAt = competition.UpdatedAt
            };

            return ApiResponse<CompetitionDetailResponse>.SuccessResponse(response);
        }

        public async Task<ApiResponse<List<CompetitionListItemResponse>>> GetListAsync(CompetitionQueryRequest query, CancellationToken cancellationToken = default)
        {
            var list = await _competitionRepository.GetListAsync(
                query.Status,
                query.CompetitionType,
                query.IsPublic,
                query.Keyword,
                cancellationToken);

            var result = list.Select(c => new CompetitionListItemResponse
            {
                CompetitionId = c.CompetitionId,
                Title = c.Title,
                CompetitionType = c.CompetitionType,
                RegistrationStart = c.RegistrationStart,
                RegistrationEnd = c.RegistrationEnd,
                StartDate = c.StartDate,
                Status = c.Status,
                IsPublic = c.IsPublic
            }).ToList();

            return ApiResponse<List<CompetitionListItemResponse>>.SuccessResponse(result);
        }

        public async Task<ApiResponse<object>> OpenRegistrationAsync(int competitionId, int currentUserId, CancellationToken cancellationToken = default)
        {
            return await UpdateStatusInternalAsync(competitionId, currentUserId, "OpenRegistration", cancellationToken);
        }

        public async Task<ApiResponse<object>> CloseRegistrationAsync(int competitionId, int currentUserId, CancellationToken cancellationToken = default)
        {
            return await UpdateStatusInternalAsync(competitionId, currentUserId, "RegistrationClosed", cancellationToken);
        }

        public async Task<ApiResponse<object>> StartCompetitionAsync(int competitionId, int currentUserId, CancellationToken cancellationToken = default)
        {
            return await UpdateStatusInternalAsync(competitionId, currentUserId, "Ongoing", cancellationToken);
        }

        public async Task<ApiResponse<object>> CompleteCompetitionAsync(int competitionId, int currentUserId, CancellationToken cancellationToken = default)
        {
            return await UpdateStatusInternalAsync(competitionId, currentUserId, "Completed", cancellationToken);
        }

        public async Task<ApiResponse<object>> CancelCompetitionAsync(int competitionId, int currentUserId, CancellationToken cancellationToken = default)
        {
            return await UpdateStatusInternalAsync(competitionId, currentUserId, "Cancelled", cancellationToken);
        }

        private async Task<ApiResponse<object>> UpdateStatusInternalAsync(int competitionId, int currentUserId, string newStatus, CancellationToken cancellationToken)
        {
            var competition = await _competitionRepository.GetByIdAsync(competitionId, cancellationToken);
            if (competition == null)
            {
                return ApiResponse<object>.FailureResponse("Competition not found.", CompetitionErrorCodes.NotFound);
            }

            if (competition.CreatedBy != currentUserId)
            {
                return ApiResponse<object>.FailureResponse("Only the competition creator may manage it.", CompetitionErrorCodes.Forbidden);
            }

            if (competition.Status == "Completed" || competition.Status == "Cancelled")
            {
                return ApiResponse<object>.FailureResponse("Completed or cancelled competitions cannot be reopened.", CompetitionErrorCodes.Conflict);
            }

            var now = DateTime.UtcNow;
            if (newStatus == "OpenRegistration")
            {
                if (competition.Status != "Draft" || now < competition.RegistrationStart || now >= competition.RegistrationEnd)
                    return ApiResponse<object>.FailureResponse("Registration can open only during its scheduled window from Draft.", CompetitionErrorCodes.Conflict);
            }
            else if (newStatus == "RegistrationClosed")
            {
                if (competition.Status != "OpenRegistration")
                    return ApiResponse<object>.FailureResponse("Only open registration can be closed.", CompetitionErrorCodes.Conflict);
            }
            else if (newStatus == "Ongoing")
            {
                if (competition.Status != "RegistrationClosed" || now < competition.StartDate)
                    return ApiResponse<object>.FailureResponse("Competition can start only after registration closes and its start time arrives.", CompetitionErrorCodes.Conflict);

                var rounds = await _competitionRepository.GetRoundsWithMatchesAsync(competitionId, cancellationToken);
                if (!await HasValidStartBracketAsync(competition, rounds, cancellationToken))
                    return ApiResponse<object>.FailureResponse("A valid bracket and eligible entrants are required before start.", CompetitionErrorCodes.Conflict);

                if (!await _competitionRepository.StartWithReadyMatchesAsync(competitionId, cancellationToken))
                    return ApiResponse<object>.FailureResponse("Competition was already started or changed.", CompetitionErrorCodes.Conflict);
                return ApiResponse<object>.SuccessResponse(new { }, "Competition status updated to Ongoing.");
            }
            else if (newStatus == "Completed")
            {
                return ApiResponse<object>.FailureResponse("Official final result and champion confirmation are required before completion.", CompetitionErrorCodes.Conflict);
            }
            else if (newStatus == "Cancelled" && competition.Status != "Draft" && competition.Status != "OpenRegistration" && competition.Status != "RegistrationClosed")
            {
                return ApiResponse<object>.FailureResponse("This competition cannot be cancelled from its current state.", CompetitionErrorCodes.Conflict);
            }

            competition.Status = newStatus;
            competition.UpdatedAt = DateTime.UtcNow;

            await _competitionRepository.UpdateAsync(competition, cancellationToken);
            return ApiResponse<object>.SuccessResponse(new { }, $"Competition status updated to {newStatus}.");
        }

        private async Task<bool> HasValidStartBracketAsync(SystemService.DAL.Entities.Competition.Competition competition, List<CompetitionRound> rounds, CancellationToken cancellationToken)
        {
            if (rounds.Count == 0 || rounds[0].RoundNumber != 1 || rounds.Select(r => r.RoundNumber).Distinct().Count() != rounds.Count)
                return false;

            for (var i = 0; i < rounds.Count; i++)
            {
                if (rounds[i].RoundNumber != i + 1 || rounds[i].Matches.Count == 0 || rounds[i].Matches.Any(m => m.CompetitionId != competition.CompetitionId || m.CompetitionRoundId != rounds[i].CompetitionRoundId))
                    return false;
            }

            var firstMatches = rounds[0].Matches;
            if (firstMatches.Any(m => m.Participants.Count is < 1 or > 2
                || m.Participants.Select(p => p.Side).Distinct().Count() != m.Participants.Count
                || m.Participants.Any(p => p.Side != "PRO" && p.Side != "CON")
                || (m.Participants.Count == 1 && (m.Status != "Bye" || m.DebateSessionId.HasValue
                    || m.WinnerUserId != m.Participants.Single().UserId || m.WinnerTeamId != m.Participants.Single().TeamId))
                || (m.Participants.Count == 2 && m.Status != "Scheduled")))
                return false;

            var bracketSize = firstMatches.Count * 2;
            var entrantCount = firstMatches.Sum(m => m.Participants.Count);
            if (entrantCount < 2 || (bracketSize & (bracketSize - 1)) != 0)
                return false;
            var expectedMatchCount = bracketSize / 2;
            for (var roundIndex = 0; roundIndex < rounds.Count; roundIndex++)
            {
                if (rounds[roundIndex].Matches.Count != expectedMatchCount
                    || (roundIndex > 0 && rounds[roundIndex].Matches.Any(m => m.Participants.Count > 2)))
                    return false;

                var nextIds = roundIndex + 1 < rounds.Count
                    ? rounds[roundIndex + 1].Matches.Select(m => m.CompetitionMatchId).ToHashSet()
                    : new HashSet<int>();
                if (rounds[roundIndex].Matches.Any(m => roundIndex + 1 < rounds.Count
                    ? !m.NextMatchId.HasValue || !nextIds.Contains(m.NextMatchId.Value)
                    : m.NextMatchId.HasValue))
                    return false;

                expectedMatchCount /= 2;
            }
            if (expectedMatchCount != 0)
                return false;

            if (competition.CompetitionType == "INDIVIDUAL")
            {
                var approved = await _registrationRepository.GetListByCompetitionAsync(competition.CompetitionId, "Approved", cancellationToken);
                var eligible = approved.Select(r => r.UserId).ToHashSet();
                var entered = firstMatches.SelectMany(m => m.Participants).Select(p => p.UserId).ToList();
                return eligible.Count == entrantCount && approved.All(r => r.User?.IsActive == true)
                    && (!competition.MaxParticipants.HasValue || eligible.Count <= competition.MaxParticipants.Value)
                    && entered.All(id => id.HasValue) && entered.Select(id => id!.Value).ToHashSet().SetEquals(eligible);
            }

            if (competition.CompetitionType == "TEAM")
            {
                var teams = await _teamRepository.GetListByCompetitionAsync(competition.CompetitionId, cancellationToken);
                var active = teams.Where(t => t.Status == "Active").ToList();
                if (active.Count != entrantCount || (competition.MaxParticipants.HasValue && active.Count * 2 > competition.MaxParticipants.Value))
                    return false;

                var users = new HashSet<int>();
                foreach (var team in active)
                {
                    var full = await _teamRepository.GetWithMembersAsync(team.TeamId, cancellationToken);
                    if (full == null || full.Captain?.IsActive != true || full.TeamMembers.Count != 1
                        || full.TeamMembers.Single().User?.IsActive != true
                        || full.CaptainUserId == full.TeamMembers.Single().UserId
                        || !users.Add(full.CaptainUserId) || !users.Add(full.TeamMembers.Single().UserId))
                        return false;
                }

                var entered = firstMatches.SelectMany(m => m.Participants).Select(p => p.TeamId).ToList();
                return entered.All(id => id.HasValue) && entered.Select(id => id!.Value).ToHashSet().SetEquals(active.Select(t => t.TeamId));
            }

            return false;
        }

        private static CompetitionResponse MapToResponse(
            SystemService.DAL.Entities.Competition.Competition c,
            string? scale = null,
            long creditsCharged = 0,
            long? remainingCredits = null)
        {
            if (scale == null && c.MaxParticipants.HasValue
                && CreditRuleCodes.TryResolveCompetitionScale(
                    c.CompetitionType, c.MaxParticipants, null, out var resolvedScale, out _, out _, out _, out _))
            {
                scale = resolvedScale;
            }

            return new CompetitionResponse
            {
                CompetitionId = c.CompetitionId,
                Title = c.Title,
                Description = c.Description,
                CreatedBy = c.CreatedBy,
                CompetitionType = c.CompetitionType,
                FormatId = c.FormatId,
                MaxParticipants = c.MaxParticipants,
                RegistrationStart = c.RegistrationStart,
                RegistrationEnd = c.RegistrationEnd,
                StartDate = c.StartDate,
                EndDate = c.EndDate,
                Status = c.Status,
                IsPublic = c.IsPublic,
                CreatedAt = c.CreatedAt,
                UpdatedAt = c.UpdatedAt,
                Scale = scale,
                CreditsCharged = creditsCharged,
                RemainingCredits = remainingCredits
            };
        }
    }
}
