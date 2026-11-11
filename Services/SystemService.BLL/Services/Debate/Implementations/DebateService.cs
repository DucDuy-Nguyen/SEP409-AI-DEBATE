using System.Collections.Concurrent;
using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Storage;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.Logging;
using System.Text.Json;
using SystemService.BLL.Common.Debate;
using SystemService.BLL.Common.Responses;
using SystemService.BLL.DTOs.AI;
using SystemService.BLL.DTOs.Debate;
using SystemService.BLL.Services.AI.Interfaces;
using SystemService.BLL.Services.Debate.Interfaces;
using SystemService.DAL.Entities.Debate;
using SystemService.DAL.Entities.Debate.Enums;
using SystemService.DAL.Repositories.Debate.Interfaces;
using SystemService.DAL.Repositories.Identity.Interfaces;
using System.Data;

namespace SystemService.BLL.Services.Debate.Implementations
{
    public class DebateService : IDebateService
    {
        private static readonly ConcurrentDictionary<string, SideSwapRequestModel> _pendingSwapRequests = new();
        private static readonly ConcurrentDictionary<int, DeliveryAnalyticsDto> _argumentDeliveryAnalytics = new();

        // User arguments have no length limit today; this caps AI speeches (~500 words) with generous headroom.
        private const int MaxAiArgumentLength = 10000;

        private readonly IDebateRepository _debateRepository;
        private readonly IUserRepository _userRepository;
        private readonly IAiEvaluatorClient? _aiEvaluatorClient;
        private readonly ILogger<DebateService>? _logger;
        private readonly DebateEvaluationCoordinator _evaluationCoordinator;

        public DebateService(
            IDebateRepository debateRepository,
            IUserRepository userRepository,
            IAiEvaluatorClient? aiEvaluatorClient = null,
            ILogger<DebateService>? logger = null,
            DebateEvaluationCoordinator? evaluationCoordinator = null)
        {
            _debateRepository = debateRepository;
            _userRepository = userRepository;
            _aiEvaluatorClient = aiEvaluatorClient;
            _logger = logger;
            // The API registers one singleton; without it the per-session lock only covers this service's own calls
            if (evaluationCoordinator == null && aiEvaluatorClient != null)
            {
                _logger?.LogWarning("DebateEvaluationCoordinator is not registered: concurrent requests may evaluate the same debate twice.");
            }
            _evaluationCoordinator = evaluationCoordinator ?? new DebateEvaluationCoordinator();
        }

        public async Task<ApiResponse<DebateSessionResponse>> CreateAiPracticeSessionAsync(
            int userId, CreateAiPracticeSessionRequest request, CancellationToken cancellationToken = default)
        {
            var user = await _userRepository.GetByIdAsync(userId, cancellationToken);
            if (user == null)
            {
                return ApiResponse<DebateSessionResponse>.FailureResponse("User not found.");
            }

            // Looking a known topic up by text creates a duplicate whenever the text differs from its description.
            Topic? topic;
            if (request.TopicId.HasValue)
            {
                topic = await _debateRepository.GetTopicByIdAsync(request.TopicId.Value, cancellationToken);
                if (topic == null || !topic.IsActive)
                {
                    return ApiResponse<DebateSessionResponse>.FailureResponse("Debate topic not found or no longer active.");
                }
            }
            else
            {
                topic = await _debateRepository.GetOrCreateTopicAsync(
                    request.Title.Trim(), request.Topic.Trim(), request.Difficulty ?? "Medium", userId, cancellationToken);
            }

            var isAi = request.IsAI;
            var formatName = isAi ? "User vs AI" : "1 vs 1";
            var formatId = isAi ? 1 : 2;

            var format = await _debateRepository.GetFormatByNameAsync(formatName, cancellationToken)
                ?? await _debateRepository.GetFormatByIdAsync(formatId, cancellationToken)
                ?? new DebateFormat { FormatId = formatId, FormatName = formatName };

            int timeLimit = request.TurnTimeLimitSeconds;
            if (timeLimit < 30 || timeLimit > 360)
            {
                timeLimit = 180;
            }

            var session = new DebateSession
            {
                TopicId = topic.TopicId,
                FormatId = format.FormatId,
                CreatedBy = userId,
                Difficulty = isAi && !string.IsNullOrWhiteSpace(request.Difficulty) ? request.Difficulty.Trim() : null,
                TurnTimeLimitSeconds = timeLimit,
                Status = SessionStatus.Waiting,
                StartTime = null,
                CreatedAt = DateTime.UtcNow
            };

            session.Participants.Add(new DebateParticipant
            {
                UserId = userId,
                ParticipantType = ParticipantType.USER,
                Side = request.UserSide,
                JoinedAt = DateTime.UtcNow
            });

            if (isAi)
            {
                var aiSide = request.UserSide == DebateSide.PRO ? DebateSide.CON : DebateSide.PRO;
                session.Participants.Add(new DebateParticipant
                {
                    UserId = null,
                    ParticipantType = ParticipantType.AI,
                    Side = aiSide,
                    JoinedAt = DateTime.UtcNow
                });
            }

            CreateStandardRounds(session);

            await _debateRepository.AddSessionAsync(session, cancellationToken);

            var fullSession = await _debateRepository.GetSessionWithDetailsAsync(session.DebateSessionId, cancellationToken);
            var message = isAi ? "AI practice debate session created. Waiting to start." : "P2P debate session created. Waiting for opponent to join.";
            return ApiResponse<DebateSessionResponse>.SuccessResponse(MapToSessionResponse(fullSession!, userId), message);
        }

        public async Task<ApiResponse<DebateSessionResponse>> CreateP2pSessionAsync(
            int userId, CreateP2pSessionRequest request, CancellationToken cancellationToken = default)
        {
            var user = await _userRepository.GetByIdAsync(userId, cancellationToken);
            if (user == null)
            {
                return ApiResponse<DebateSessionResponse>.FailureResponse("User not found.");
            }

            var (topic, topicError) = await ResolveTopicAsync(request.TopicId, request.Title, request.Topic, userId, cancellationToken);
            if (topic == null)
            {
                return ApiResponse<DebateSessionResponse>.FailureResponse(topicError!);
            }

            var isAi = request.IsAI;
            var formatName = isAi ? "User vs AI" : "1 vs 1";
            var formatId = isAi ? 1 : 2;

            var format = await _debateRepository.GetFormatByNameAsync(formatName, cancellationToken)
                ?? await _debateRepository.GetFormatByIdAsync(formatId, cancellationToken)
                ?? new DebateFormat { FormatId = formatId, FormatName = formatName };

            int timeLimit = request.TurnTimeLimitSeconds;
            if (timeLimit < 30 || timeLimit > 360)
            {
                timeLimit = 180;
            }

            var session = new DebateSession
            {
                TopicId = topic.TopicId,
                FormatId = format.FormatId,
                CreatedBy = userId,
                TurnTimeLimitSeconds = timeLimit,
                Status = SessionStatus.Waiting,
                StartTime = null,
                CreatedAt = DateTime.UtcNow
            };

            session.Participants.Add(new DebateParticipant
            {
                UserId = userId,
                ParticipantType = ParticipantType.USER,
                Side = request.UserSide,
                JoinedAt = DateTime.UtcNow
            });

            if (isAi)
            {
                var aiSide = request.UserSide == DebateSide.PRO ? DebateSide.CON : DebateSide.PRO;
                session.Participants.Add(new DebateParticipant
                {
                    UserId = null,
                    ParticipantType = ParticipantType.AI,
                    Side = aiSide,
                    JoinedAt = DateTime.UtcNow
                });
            }

            CreateStandardRounds(session);

            await _debateRepository.AddSessionAsync(session, cancellationToken);

            var fullSession = await _debateRepository.GetSessionWithDetailsAsync(session.DebateSessionId, cancellationToken);
            var message = isAi ? "Debate session created with AI opponent. Waiting to start." : "P2P debate session created. Waiting for opponent to join.";
            return ApiResponse<DebateSessionResponse>.SuccessResponse(MapToSessionResponse(fullSession!, userId), message);
        }

        public async Task<ApiResponse<DebateSessionResponse>> JoinP2pSessionAsync(
            int userId, int sessionId, JoinSessionRequest request, CancellationToken cancellationToken = default)
        {
            var user = await _userRepository.GetByIdAsync(userId, cancellationToken);
            if (user == null)
            {
                return ApiResponse<DebateSessionResponse>.FailureResponse("User not found.");
            }

            // Same lock as leaving: saving a session loaded before a leave would overwrite Cancelled with Waiting.
            using var transaction = await _debateRepository.BeginTransactionAsync(cancellationToken);
            await _debateRepository.LockSessionForUpdateAsync(sessionId, cancellationToken);

            var session = await _debateRepository.GetSessionWithDetailsAsync(sessionId, cancellationToken);
            if (session == null)
            {
                return ApiResponse<DebateSessionResponse>.FailureResponse("Debate session not found.");
            }

            var isCompetition = await _debateRepository.IsSessionInCompetitionAsync(sessionId, cancellationToken);
            if (isCompetition)
            {
                return ApiResponse<DebateSessionResponse>.FailureResponse("Phiên tranh biện này thuộc giải đấu. Người tham gia đã được chỉ định tự động.");
            }

            if (session.Status != SessionStatus.Waiting)
            {
                return ApiResponse<DebateSessionResponse>.FailureResponse($"Debate session is not open for joining (Status: {session.Status}).");
            }

            if (session.Participants.Count >= 2)
            {
                return ApiResponse<DebateSessionResponse>.FailureResponse("Debate session is already full.");
            }

            if (session.CreatedBy == userId)
            {
                return ApiResponse<DebateSessionResponse>.FailureResponse("Room creator cannot join as the second participant.");
            }

            if (session.Participants.Any(p => p.UserId == userId))
            {
                return ApiResponse<DebateSessionResponse>.FailureResponse("User is already a participant in this session.");
            }

            var existingParticipant = session.Participants.First();
            var assignedSide = existingParticipant.Side == DebateSide.PRO ? DebateSide.CON : DebateSide.PRO;

            var newParticipant = new DebateParticipant
            {
                DebateSessionId = sessionId,
                UserId = userId,
                ParticipantType = ParticipantType.USER,
                Side = assignedSide,
                JoinedAt = DateTime.UtcNow
            };

            await _debateRepository.AddParticipantAsync(newParticipant, cancellationToken);

            // Session remains in Waiting status until the room creator starts it.
            await _debateRepository.UpdateSessionAsync(session, cancellationToken);
            await transaction.CommitAsync(cancellationToken);

            var updatedSession = await _debateRepository.GetSessionWithDetailsAsync(sessionId, cancellationToken);
            return ApiResponse<DebateSessionResponse>.SuccessResponse(MapToSessionResponse(updatedSession!, userId), "Joined P2P debate session successfully.");
        }

        public async Task<ApiResponse<DebateSessionResponse>> GetSessionDetailsAsync(int userId, int sessionId, CancellationToken cancellationToken = default)
        {
            var session = await _debateRepository.GetSessionWithDetailsAsync(sessionId, cancellationToken);
            if (session == null)
            {
                return ApiResponse<DebateSessionResponse>.FailureResponse("Debate session not found.");
            }

            return ApiResponse<DebateSessionResponse>.SuccessResponse(MapToSessionResponse(session, userId), "Session details retrieved.");
        }

        public async Task<ApiResponse<DebateSessionResponse>> SubmitArgumentAsync(
            int userId, int sessionId, SubmitArgumentRequest request, CancellationToken cancellationToken = default)
        {
            using var transaction = await _debateRepository.BeginTransactionAsync(cancellationToken);
            try
            {
                await _debateRepository.LockSessionForUpdateAsync(sessionId, cancellationToken);

                var session = await _debateRepository.GetSessionWithDetailsAsync(sessionId, cancellationToken);
                if (session == null)
                {
                    return ApiResponse<DebateSessionResponse>.FailureResponse("Debate session not found.", new ApiErrorDetail(DebateErrorCodes.SessionNotFound));
                }

                if (session.Status != SessionStatus.InProgress)
                {
                    return ApiResponse<DebateSessionResponse>.FailureResponse("Debate session is not currently in progress.", new ApiErrorDetail(DebateErrorCodes.SessionNotInProgress));
                }

                var participant = session.Participants.FirstOrDefault(p => p.UserId == userId);
                if (participant == null)
                {
                    return ApiResponse<DebateSessionResponse>.FailureResponse("You are not a participant in this debate session.", new ApiErrorDetail(DebateErrorCodes.NotParticipant));
                }

                // 2v2 has 4 speakers per round and does not follow DebateTurnOrder; keep its original logic.
                if (!IsOneVsOne(session))
                {
                    return await SubmitTeamArgumentAsync(userId, sessionId, session, participant, request, transaction, cancellationToken);
                }

                int submittedCount = CountArguments(session);
                var nextTurn = DebateTurnOrder.GetNextTurn(submittedCount);
                if (nextTurn == null)
                {
                    session.Status = SessionStatus.Completed;
                    session.EndTime = DateTime.UtcNow;
                    await _debateRepository.UpdateSessionAsync(session, cancellationToken);
                    await transaction.CommitAsync(cancellationToken);
                    return ApiResponse<DebateSessionResponse>.FailureResponse(
                        $"All {DebateTurnOrder.TotalTurns} turns in this debate session have already been completed.",
                        new ApiErrorDetail(DebateErrorCodes.SessionCompleted));
                }

                if (participant.Side != nextTurn.Side)
                {
                    return ApiResponse<DebateSessionResponse>.FailureResponse(
                        $"It is not your turn to submit an argument. Current turn belongs to {SideName(nextTurn.Side)}.",
                        new ApiErrorDetail(DebateErrorCodes.NotYourTurn));
                }

                string trimmedContent = request.Content?.Trim() ?? string.Empty;
                if (trimmedContent.Length == 0)
                {
                    return ApiResponse<DebateSessionResponse>.FailureResponse("Argument content must not be empty.", new ApiErrorDetail(DebateErrorCodes.InvalidRequest));
                }

                var argument = await AddTurnArgumentAsync(
                    session, participant, nextTurn, submittedCount, trimmedContent, isTimed: true,
                    cancellationToken, request.DurationSeconds, request.DeliveryAnalytics);
                if (argument == null)
                {
                    return ApiResponse<DebateSessionResponse>.FailureResponse($"Round {nextTurn.RoundNumber} is missing for this debate session.");
                }

                bool isSessionCompleted = session.Status == SessionStatus.Completed;
                await transaction.CommitAsync(cancellationToken);

                // The debate is over: it is graded in the background (own DI scope), the response does not wait for it.
                // GET /evaluation awaits that same evaluation, or starts a new one if it failed.
                if (isSessionCompleted && _aiEvaluatorClient != null)
                {
                    StartBackgroundEvaluation(sessionId);
                }

                var updatedSession = await _debateRepository.GetSessionWithDetailsAsync(sessionId, cancellationToken);
                return ApiResponse<DebateSessionResponse>.SuccessResponse(MapToSessionResponse(updatedSession!, userId), "Argument submitted successfully.");
            }
            catch (DbUpdateException)
            {
                await transaction.RollbackAsync(cancellationToken);
                return ApiResponse<DebateSessionResponse>.FailureResponse("An argument for this turn has already been submitted or a concurrent submission occurred.", new ApiErrorDetail(DebateErrorCodes.ConcurrentSubmission));
            }
            catch (Exception ex)
            {
                await transaction.RollbackAsync(cancellationToken);
                return ApiResponse<DebateSessionResponse>.FailureResponse($"Failed to submit argument: {ex.Message}");
            }
        }

        public async Task<ApiResponse<SubmitAiArgumentResponse>> SubmitAiArgumentAsync(
            int userId, int sessionId, SubmitAiArgumentRequest request, CancellationToken cancellationToken = default)
        {
            string content = request?.Content?.Trim() ?? string.Empty;
            if (content.Length == 0)
            {
                return AiArgumentFailure("AI argument content must not be empty.", DebateErrorCodes.InvalidRequest);
            }

            if (content.Length > MaxAiArgumentLength)
            {
                return AiArgumentFailure($"AI argument content must not exceed {MaxAiArgumentLength} characters.", DebateErrorCodes.InvalidRequest);
            }

            var turn = request!.TurnIndex.HasValue ? DebateTurnOrder.GetTurn(request.TurnIndex.Value) : null;
            if (turn == null)
            {
                return AiArgumentFailure($"turnIndex is required and must be between 0 and {DebateTurnOrder.TotalTurns - 1}.", DebateErrorCodes.InvalidRequest);
            }

            using var transaction = await _debateRepository.BeginTransactionAsync(cancellationToken);
            try
            {
                // Serializes concurrent retries for the same turn so the idempotency check below sees the first insert.
                await _debateRepository.LockSessionForUpdateAsync(sessionId, cancellationToken);

                var session = await _debateRepository.GetSessionWithDetailsAsync(sessionId, cancellationToken);
                if (session == null)
                {
                    return AiArgumentFailure("Debate session not found.", DebateErrorCodes.SessionNotFound);
                }

                var participant = session.Participants.FirstOrDefault(p => p.UserId == userId && p.ParticipantType == ParticipantType.USER);
                if (participant == null)
                {
                    return AiArgumentFailure("You are not a participant in this debate session.", DebateErrorCodes.NotParticipant);
                }

                var aiParticipant = IsOneVsOne(session)
                    ? session.Participants.FirstOrDefault(p => p.ParticipantType == ParticipantType.AI)
                    : null;
                if (aiParticipant == null)
                {
                    return AiArgumentFailure("AI arguments can only be recorded for 1v1 AI practice sessions.", DebateErrorCodes.NotAiSession);
                }

                if (turn.Side != aiParticipant.Side)
                {
                    return AiArgumentFailure(
                        $"Turn {turn.TurnIndex} belongs to {SideName(turn.Side)}, not to the AI ({SideName(aiParticipant.Side)}).",
                        DebateErrorCodes.NotAiTurn);
                }

                var orderedArguments = GetOrderedArguments(session);

                // Idempotent retry: the AI argument for this turn already exists, return it unchanged.
                // Checked before the status check so a retry of the final turn still succeeds after the session completed.
                if (turn.TurnIndex < orderedArguments.Count)
                {
                    var existing = orderedArguments[turn.TurnIndex];
                    if (existing.ParticipantId != aiParticipant.ParticipantId)
                    {
                        return AiArgumentFailure($"Turn {turn.TurnIndex} is already recorded for another participant.", DebateErrorCodes.TurnOutOfOrder);
                    }

                    var existingRound = session.DebateRounds.First(r => r.RoundId == existing.RoundId);
                    return await AiArgumentSuccessAsync(userId, sessionId, turn.TurnIndex, existing, existingRound, aiParticipant,
                        alreadyRecorded: true, "AI argument for this turn was already recorded.", cancellationToken);
                }

                if (session.Status != SessionStatus.InProgress)
                {
                    return AiArgumentFailure("Debate session is not currently in progress.", DebateErrorCodes.SessionNotInProgress);
                }

                if (turn.TurnIndex > orderedArguments.Count)
                {
                    var expectedTurn = DebateTurnOrder.GetNextTurn(orderedArguments.Count)!;
                    return AiArgumentFailure(
                        $"Turn {turn.TurnIndex} is not the next turn. Expected turn {expectedTurn.TurnIndex} ({SideName(expectedTurn.Side)}).",
                        DebateErrorCodes.TurnOutOfOrder);
                }

                var argument = await AddTurnArgumentAsync(session, aiParticipant, turn, orderedArguments.Count, content, isTimed: false, cancellationToken);
                if (argument == null)
                {
                    return AiArgumentFailure($"Round {turn.RoundNumber} is missing for this debate session.", DebateErrorCodes.InvalidRequest);
                }

                bool isSessionCompleted = session.Status == SessionStatus.Completed;
                await transaction.CommitAsync(cancellationToken);

                // The debate is over: it is graded in the background (own DI scope), the response does not wait for it.
                // GET /evaluation awaits that same evaluation, or starts a new one if it failed.
                if (isSessionCompleted && _aiEvaluatorClient != null)
                {
                    StartBackgroundEvaluation(sessionId);
                }

                var round = session.DebateRounds.First(r => r.RoundNumber == turn.RoundNumber);
                return await AiArgumentSuccessAsync(userId, sessionId, turn.TurnIndex, argument, round, aiParticipant,
                    alreadyRecorded: false, "AI argument recorded successfully.", cancellationToken);
            }
            catch (DbUpdateException)
            {
                await transaction.RollbackAsync(cancellationToken);
                return AiArgumentFailure("A concurrent submission occurred for this turn. Retry the request.", DebateErrorCodes.ConcurrentSubmission);
            }
            // Other exceptions propagate to ExceptionMiddleware (logged, 500, message hidden outside Development);
            // the undisposed transaction is rolled back when it is disposed.
        }

        // Any participant leaving cancels the session for everyone, 2v2 and a host leaving a waiting room included.
        public async Task<ApiResponse<DebateSessionResponse>> LeaveSessionAsync(
            int userId, int sessionId, CancellationToken cancellationToken = default)
        {
            using var transaction = await _debateRepository.BeginTransactionAsync(cancellationToken);

            // Same lock as submitting a turn, so the final turn and a leave cannot both win.
            await _debateRepository.LockSessionForUpdateAsync(sessionId, cancellationToken);

            var session = await _debateRepository.GetSessionWithDetailsAsync(sessionId, cancellationToken);
            if (session == null)
            {
                return ApiResponse<DebateSessionResponse>.FailureResponse("Debate session not found.", new ApiErrorDetail(DebateErrorCodes.SessionNotFound));
            }

            if (!session.Participants.Any(p => p.UserId == userId))
            {
                return ApiResponse<DebateSessionResponse>.FailureResponse("You are not a participant in this debate session.", new ApiErrorDetail(DebateErrorCodes.NotParticipant));
            }

            if (session.Status == SessionStatus.Completed)
            {
                return ApiResponse<DebateSessionResponse>.FailureResponse("Debate session is already completed and cannot be left.", new ApiErrorDetail(DebateErrorCodes.SessionCompleted));
            }

            if (session.Status == SessionStatus.Cancelled)
            {
                return ApiResponse<DebateSessionResponse>.SuccessResponse(MapToSessionResponse(session, userId), "Debate session was already cancelled.");
            }

            session.Status = SessionStatus.Cancelled;
            session.EndTime = DateTime.UtcNow;
            session.UpdatedAt = session.EndTime;
            await _debateRepository.UpdateSessionAsync(session, cancellationToken);
            await transaction.CommitAsync(cancellationToken);

            return ApiResponse<DebateSessionResponse>.SuccessResponse(MapToSessionResponse(session, userId), "Left the debate session. It has been cancelled.");
        }

        private async Task<ApiResponse<DebateSessionResponse>> SubmitTeamArgumentAsync(
            int userId, int sessionId, DebateSession session, DebateParticipant participant, SubmitArgumentRequest request,
            IDbContextTransaction transaction, CancellationToken cancellationToken)
        {
            int maxArgsPerRound = GetMaxArgsPerRound(session);

            var currentRound = session.DebateRounds
                .OrderBy(r => r.RoundNumber)
                .FirstOrDefault(r => r.Arguments.Count < maxArgsPerRound);

            if (currentRound == null)
            {
                session.Status = SessionStatus.Completed;
                session.EndTime = DateTime.UtcNow;
                await _debateRepository.UpdateSessionAsync(session, cancellationToken);
                await transaction.CommitAsync(cancellationToken);
                return ApiResponse<DebateSessionResponse>.FailureResponse("All rounds in this debate session have already been completed.");
            }

            var expectedTurnSide = DebateSide.PRO;
            if (currentRound.Arguments.Any())
            {
                var lastSubmittedSide = currentRound.Arguments.Last().Participant.Side;
                expectedTurnSide = lastSubmittedSide == DebateSide.PRO ? DebateSide.CON : DebateSide.PRO;
            }

            if (participant.Side != expectedTurnSide)
            {
                return ApiResponse<DebateSessionResponse>.FailureResponse($"It is not your turn to submit an argument. Current turn belongs to {expectedTurnSide}.");
            }

            if (currentRound.Arguments.Any(a => a.ParticipantId == participant.ParticipantId))
            {
                return ApiResponse<DebateSessionResponse>.FailureResponse("You have already submitted an argument for this round.");
            }

            string trimmedContent = request.Content.Trim();
            int wordCount = trimmedContent.Split(new[] { ' ', '\t', '\n', '\r' }, StringSplitOptions.RemoveEmptyEntries).Length;

            int durationSeconds = request.DurationSeconds is > 0 ? request.DurationSeconds.Value : 30;
            if (!request.DurationSeconds.HasValue && currentRound.StartTime.HasValue)
            {
                durationSeconds = (int)Math.Max(1, (DateTime.UtcNow - currentRound.StartTime.Value).TotalSeconds);
            }

            var argument = new Argument
            {
                RoundId = currentRound.RoundId,
                ParticipantId = participant.ParticipantId,
                Content = trimmedContent,
                WordCount = wordCount,
                DurationSeconds = durationSeconds,
                SubmittedAt = DateTime.UtcNow
            };

            await _debateRepository.AddArgumentAsync(argument, cancellationToken);
            if (request.DeliveryAnalytics != null && argument.ArgumentId > 0)
            {
                _argumentDeliveryAnalytics[argument.ArgumentId] = request.DeliveryAnalytics;
            }

            if (currentRound.Arguments.Count + 1 >= maxArgsPerRound)
            {
                currentRound.EndTime = DateTime.UtcNow;
                await _debateRepository.UpdateRoundAsync(currentRound, cancellationToken);

                var nextRound = session.DebateRounds.FirstOrDefault(r => r.RoundNumber == currentRound.RoundNumber + 1);
                if (nextRound != null)
                {
                    nextRound.StartTime = DateTime.UtcNow;
                    await _debateRepository.UpdateRoundAsync(nextRound, cancellationToken);
                }
                else
                {
                    var completedAt = DateTime.UtcNow;
                    session.Status = SessionStatus.Completed;
                    session.EndTime = completedAt;
                    await _debateRepository.UpdateLinkedMatchStatusOnSessionCompleteAsync(sessionId, completedAt, cancellationToken);
                    await _debateRepository.UpdateSessionAsync(session, cancellationToken);
                }
            }

            bool isSessionCompleted = session.Status == SessionStatus.Completed;
            await transaction.CommitAsync(cancellationToken);

            // The debate is over: it is graded in the background (own DI scope), the response does not wait for it.
            // GET /evaluation awaits that same evaluation, or starts a new one if it failed.
            if (isSessionCompleted && _aiEvaluatorClient != null)
            {
                StartBackgroundEvaluation(sessionId);
            }

            var updatedSession = await _debateRepository.GetSessionWithDetailsAsync(sessionId, cancellationToken);
            return ApiResponse<DebateSessionResponse>.SuccessResponse(MapToSessionResponse(updatedSession!, userId), "Argument submitted successfully.");
        }

        public async Task<ApiResponse<DebateSessionResponse>> Create2v2SessionAsync(
            int userId, Create2v2SessionRequest request, CancellationToken cancellationToken = default)
        {
            var user = await _userRepository.GetByIdAsync(userId, cancellationToken);
            if (user == null)
            {
                return ApiResponse<DebateSessionResponse>.FailureResponse("User not found.");
            }

            var (topic, topicError) = await ResolveTopicAsync(request.TopicId, request.Title, request.Topic, userId, cancellationToken);
            if (topic == null)
            {
                return ApiResponse<DebateSessionResponse>.FailureResponse(topicError!);
            }

            var formatName = "2 vs 2";
            var format = await _debateRepository.GetOrCreateFormatAsync(
                formatName, maxParticipants: 4, totalRounds: 3, roundDurationSeconds: request.TurnTimeLimitSeconds, cancellationToken);

            int timeLimit = request.TurnTimeLimitSeconds;
            if (timeLimit < 30 || timeLimit > 360)
            {
                timeLimit = 180;
            }

            var isAi = request.IsAI;

            var session = new DebateSession
            {
                TopicId = topic.TopicId,
                FormatId = format.FormatId,
                CreatedBy = userId,
                TurnTimeLimitSeconds = timeLimit,
                Status = SessionStatus.Waiting,
                StartTime = null,
                CreatedAt = DateTime.UtcNow
            };

            session.Participants.Add(new DebateParticipant
            {
                UserId = userId,
                ParticipantType = ParticipantType.USER,
                Side = request.UserSide,
                JoinedAt = DateTime.UtcNow
            });

            if (isAi)
            {
                var opponentSide = request.UserSide == DebateSide.PRO ? DebateSide.CON : DebateSide.PRO;

                session.Participants.Add(new DebateParticipant
                {
                    UserId = null,
                    ParticipantType = ParticipantType.AI,
                    Side = opponentSide,
                    JoinedAt = DateTime.UtcNow
                });

                session.Participants.Add(new DebateParticipant
                {
                    UserId = null,
                    ParticipantType = ParticipantType.AI,
                    Side = opponentSide,
                    JoinedAt = DateTime.UtcNow
                });
            }

            CreateStandardRounds(session);

            await _debateRepository.AddSessionAsync(session, cancellationToken);

            var fullSession = await _debateRepository.GetSessionWithDetailsAsync(session.DebateSessionId, cancellationToken);
            var message = isAi ? "2v2 AI debate session created. Waiting for human teammate to join or start." : "2v2 P2P debate session created. Waiting for other participants to join.";
            return ApiResponse<DebateSessionResponse>.SuccessResponse(MapToSessionResponse(fullSession!, userId), message);
        }

        public async Task<ApiResponse<DebateSessionResponse>> Join2v2SessionAsync(
            int userId, int sessionId, Join2v2SessionRequest request, CancellationToken cancellationToken = default)
        {
            var user = await _userRepository.GetByIdAsync(userId, cancellationToken);
            if (user == null)
            {
                return ApiResponse<DebateSessionResponse>.FailureResponse("User not found.");
            }

            // Same lock as leaving: saving a session loaded before a leave would overwrite Cancelled with Waiting.
            using var transaction = await _debateRepository.BeginTransactionAsync(cancellationToken);
            await _debateRepository.LockSessionForUpdateAsync(sessionId, cancellationToken);

            var session = await _debateRepository.GetSessionWithDetailsAsync(sessionId, cancellationToken);
            if (session == null)
            {
                return ApiResponse<DebateSessionResponse>.FailureResponse("Debate session not found.");
            }

            var isCompetition = await _debateRepository.IsSessionInCompetitionAsync(sessionId, cancellationToken);
            if (isCompetition)
            {
                return ApiResponse<DebateSessionResponse>.FailureResponse("Phiên tranh biện này thuộc giải đấu. Người tham gia đã được chỉ định tự động.");
            }

            if (session.Status != SessionStatus.Waiting)
            {
                return ApiResponse<DebateSessionResponse>.FailureResponse($"Debate session is not open for joining (Status: {session.Status}).");
            }

            int maxParticipants = 4;
            if (session.Format != null && session.Format.MaxParticipants > 0 && !session.Format.FormatName.Contains("Solo"))
            {
                maxParticipants = Math.Max(4, session.Format.MaxParticipants);
            }

            if (session.Participants.Count >= maxParticipants)
            {
                return ApiResponse<DebateSessionResponse>.FailureResponse("Debate session is already full.");
            }

            if (session.Participants.Any(p => p.UserId == userId))
            {
                return ApiResponse<DebateSessionResponse>.FailureResponse("User is already a participant in this session.");
            }

            var proCount = session.Participants.Count(p => p.Side == DebateSide.PRO);
            var conCount = session.Participants.Count(p => p.Side == DebateSide.CON);

            DebateSide assignedSide;
            if (request.PreferredSide.HasValue)
            {
                if (request.PreferredSide.Value == DebateSide.PRO && proCount < 2)
                    assignedSide = DebateSide.PRO;
                else if (request.PreferredSide.Value == DebateSide.CON && conCount < 2)
                    assignedSide = DebateSide.CON;
                else
                    assignedSide = proCount <= conCount ? DebateSide.PRO : DebateSide.CON;
            }
            else
            {
                assignedSide = proCount <= conCount ? DebateSide.PRO : DebateSide.CON;
            }

            var newParticipant = new DebateParticipant
            {
                DebateSessionId = sessionId,
                UserId = userId,
                ParticipantType = ParticipantType.USER,
                Side = assignedSide,
                JoinedAt = DateTime.UtcNow
            };

            await _debateRepository.AddParticipantAsync(newParticipant, cancellationToken);

            // Session remains in Waiting status until the room creator starts it.
            await _debateRepository.UpdateSessionAsync(session, cancellationToken);
            await transaction.CommitAsync(cancellationToken);

            var updatedSession = await _debateRepository.GetSessionWithDetailsAsync(sessionId, cancellationToken);
            return ApiResponse<DebateSessionResponse>.SuccessResponse(MapToSessionResponse(updatedSession!, userId), "Joined 2v2 debate session successfully.");
        }

        public async Task<ApiResponse<DebateTranscriptResponse>> GetTranscriptAsync(int userId, int sessionId, CancellationToken cancellationToken = default)
        {
            var session = await _debateRepository.GetSessionWithDetailsAsync(sessionId, cancellationToken);
            if (session == null)
            {
                return ApiResponse<DebateTranscriptResponse>.FailureResponse("Debate session not found.");
            }

            var transcript = new DebateTranscriptResponse
            {
                SessionId = session.DebateSessionId,
                Title = session.Topic?.Title ?? "Debate Session",
                Topic = session.Topic?.Description ?? session.Topic?.Title ?? string.Empty,
                Status = session.Status,
                Arguments = session.DebateRounds
                    .SelectMany(r => r.Arguments.Select(a => new ArgumentDetailDto
                    {
                        ArgumentId = a.ArgumentId,
                        TurnOrder = r.RoundNumber,
                        Stage = MapRoundTypeToStage(r.RoundType),
                        Side = a.Participant.Side,
                        UserId = a.Participant.UserId,
                        SpeakerName = a.Participant.ParticipantType == ParticipantType.AI ? "AI Opponent" : (a.Participant.User?.FullName ?? "Unknown User"),
                        IsAI = a.Participant.ParticipantType == ParticipantType.AI,
                        Content = a.Content,
                        WordCount = a.WordCount,
                        DurationSeconds = a.DurationSeconds,
                        DeliveryAnalytics = _argumentDeliveryAnalytics.TryGetValue(a.ArgumentId, out var da) ? da : null,
                        SubmittedAt = a.SubmittedAt
                    }))
                    .OrderBy(a => a.TurnOrder)
                    .ThenBy(a => a.SubmittedAt)
                    .ToList()
            };

            return ApiResponse<DebateTranscriptResponse>.SuccessResponse(transcript, "Transcript retrieved successfully.");
        }

        public async Task<ApiResponse<List<DebateHistoryItemDto>>> GetUserHistoryAsync(int userId, CancellationToken cancellationToken = default)
        {
            var sessions = await _debateRepository.GetUserSessionsAsync(userId, cancellationToken);

            var history = sessions.Select(s =>
            {
                var myParticipant = s.Participants.FirstOrDefault(p => p.UserId == userId);
                return new DebateHistoryItemDto
                {
                    SessionId = s.DebateSessionId,
                    Title = s.Topic?.Title ?? "Debate Session",
                    Topic = s.Topic?.Description ?? s.Topic?.Title ?? string.Empty,
                    DebateType = InferDebateType(s),
                    Status = s.Status,
                    UserSide = myParticipant?.Side ?? DebateSide.PRO,
                    CreatedAt = s.CreatedAt,
                    EndedAt = s.EndTime
                };
            }).ToList();

            return ApiResponse<List<DebateHistoryItemDto>>.SuccessResponse(history, "User debate history retrieved successfully.");
        }

        #region Helper Methods

        private void CreateStandardRounds(DebateSession session)
        {
            var roundTypes = new[] { RoundType.OPENING, RoundType.REBUTTAL, RoundType.CLOSING };
            for (int i = 0; i < roundTypes.Length; i++)
            {
                int roundNumber = i + 1;
                session.DebateRounds.Add(new DebateRound
                {
                    RoundNumber = roundNumber,
                    RoundType = roundTypes[i],
                    CreatedAt = DateTime.UtcNow,
                    StartTime = roundNumber == 1 && session.Status == SessionStatus.InProgress ? DateTime.UtcNow : null
                });
            }
        }

        private DebateStage MapRoundTypeToStage(RoundType roundType)
        {
            return roundType switch
            {
                RoundType.OPENING => DebateStage.Opening,
                RoundType.REBUTTAL => DebateStage.Rebuttal,
                RoundType.CLOSING => DebateStage.Closing,
                _ => DebateStage.Opening
            };
        }

        private static int GetMaxArgsPerRound(DebateSession session)
        {
            return session.Format?.MaxParticipants > 0 ? session.Format.MaxParticipants : 2;
        }

        // 1v1 sessions (User vs AI, P2P 1v1, Direct1v1) follow DebateTurnOrder; 2v2 does not.
        private static bool IsOneVsOne(DebateSession session)
        {
            return GetMaxArgsPerRound(session) == 2 && session.Participants.Count <= 2;
        }

        // DebateSession has no column for its type, so it is derived. 2v2 has no enum value and reports P2pMatch,
        // even with AI participants. Direct1v1 is not distinguished yet and also reports P2pMatch.
        private DebateType InferDebateType(DebateSession session)
        {
            if (_debateRepository.IsSessionInCompetition(session.DebateSessionId))
            {
                return DebateType.Competition;
            }

            return IsOneVsOne(session) && session.Participants.Any(p => p.ParticipantType == ParticipantType.AI)
                ? DebateType.AiPractice
                : DebateType.P2pMatch;
        }

        private static int CountArguments(DebateSession session)
        {
            return session.DebateRounds.Sum(r => r.Arguments.Count);
        }

        private static List<Argument> GetOrderedArguments(DebateSession session)
        {
            return session.DebateRounds
                .OrderBy(r => r.RoundNumber)
                .SelectMany(r => r.Arguments.OrderBy(a => a.SubmittedAt).ThenBy(a => a.ArgumentId))
                .ToList();
        }

        // DebateSide has duplicate values (PRO/Affirmative, CON/Negative), so ToString() is ambiguous.
        private static string SideName(DebateSide side)
        {
            return side == DebateSide.CON ? "CON" : "PRO";
        }

        /// <summary>
        /// Saves the argument for <paramref name="turn"/> and advances round/session state.
        /// <paramref name="submittedCount"/> is the argument count before this insert; it is used instead of
        /// round.Arguments.Count because EF fixup may already have added the new argument to that collection.
        /// Returns null if the round for this turn does not exist.
        /// </summary>
        private async Task<Argument?> AddTurnArgumentAsync(
            DebateSession session, DebateParticipant participant, DebateTurnSlot turn, int submittedCount,
            string content, bool isTimed, CancellationToken cancellationToken,
            int? explicitDurationSeconds = null, DeliveryAnalyticsDto? deliveryAnalytics = null)
        {
            var round = session.DebateRounds.FirstOrDefault(r => r.RoundNumber == turn.RoundNumber);
            if (round == null)
            {
                return null;
            }

            int wordCount = content.Split(new[] { ' ', '\t', '\n', '\r' }, StringSplitOptions.RemoveEmptyEntries).Length;

            int? durationSeconds = explicitDurationSeconds is > 0 ? explicitDurationSeconds : null;
            if (!durationSeconds.HasValue && isTimed)
            {
                durationSeconds = 30;
                if (round.StartTime.HasValue)
                {
                    durationSeconds = (int)Math.Max(1, (DateTime.UtcNow - round.StartTime.Value).TotalSeconds);
                }
            }

            var argument = new Argument
            {
                RoundId = round.RoundId,
                ParticipantId = participant.ParticipantId,
                Content = content,
                WordCount = wordCount,
                DurationSeconds = durationSeconds,
                SubmittedAt = DateTime.UtcNow
            };

            await _debateRepository.AddArgumentAsync(argument, cancellationToken);
            if (deliveryAnalytics != null && argument.ArgumentId > 0)
            {
                _argumentDeliveryAnalytics[argument.ArgumentId] = deliveryAnalytics;
            }

            var followingTurn = DebateTurnOrder.GetNextTurn(submittedCount + 1);
            if (followingTurn != null && followingTurn.RoundNumber == turn.RoundNumber)
            {
                return argument;
            }

            var now = DateTime.UtcNow;
            round.EndTime = now;
            await _debateRepository.UpdateRoundAsync(round, cancellationToken);

            var nextRound = followingTurn == null
                ? null
                : session.DebateRounds.FirstOrDefault(r => r.RoundNumber == followingTurn.RoundNumber);

            if (nextRound != null)
            {
                nextRound.StartTime = now;
                await _debateRepository.UpdateRoundAsync(nextRound, cancellationToken);
            }
            else
            {
                session.Status = SessionStatus.Completed;
                session.EndTime = now;
                await _debateRepository.UpdateLinkedMatchStatusOnSessionCompleteAsync(session.DebateSessionId, now, cancellationToken);
                await _debateRepository.UpdateSessionAsync(session, cancellationToken);
            }

            return argument;
        }

        private ArgumentDetailDto MapToArgumentDetail(Argument argument, DebateRound round, DebateParticipant participant)
        {
            return new ArgumentDetailDto
            {
                ArgumentId = argument.ArgumentId,
                TurnOrder = round.RoundNumber,
                Stage = MapRoundTypeToStage(round.RoundType),
                Side = participant.Side,
                UserId = participant.UserId,
                SpeakerName = participant.ParticipantType == ParticipantType.AI ? "AI Opponent" : (participant.User?.FullName ?? "Unknown User"),
                IsAI = participant.ParticipantType == ParticipantType.AI,
                Content = argument.Content,
                WordCount = argument.WordCount,
                DurationSeconds = argument.DurationSeconds,
                DeliveryAnalytics = _argumentDeliveryAnalytics.TryGetValue(argument.ArgumentId, out var da) ? da : null,
                SubmittedAt = argument.SubmittedAt
            };
        }

        private static ApiResponse<SubmitAiArgumentResponse> AiArgumentFailure(string message, string code)
        {
            return ApiResponse<SubmitAiArgumentResponse>.FailureResponse(message, new ApiErrorDetail(code));
        }

        private async Task<ApiResponse<SubmitAiArgumentResponse>> AiArgumentSuccessAsync(
            int userId, int sessionId, int turnIndex, Argument argument, DebateRound round, DebateParticipant aiParticipant,
            bool alreadyRecorded, string message, CancellationToken cancellationToken)
        {
            var updatedSession = await _debateRepository.GetSessionWithDetailsAsync(sessionId, cancellationToken);
            var response = new SubmitAiArgumentResponse
            {
                TurnIndex = turnIndex,
                AlreadyRecorded = alreadyRecorded,
                Argument = MapToArgumentDetail(argument, round, aiParticipant),
                Session = MapToSessionResponse(updatedSession!, userId)
            };
            return ApiResponse<SubmitAiArgumentResponse>.SuccessResponse(response, message);
        }

        private DebateSessionResponse MapToSessionResponse(DebateSession session, int currentUserId)
        {
            DebateRound? currentRound;
            var currentTurnSide = DebateSide.PRO;
            int? currentTurnIndex = null;

            if (IsOneVsOne(session))
            {
                var nextTurn = DebateTurnOrder.GetNextTurn(CountArguments(session));
                currentRound = nextTurn == null ? null : session.DebateRounds.FirstOrDefault(r => r.RoundNumber == nextTurn.RoundNumber);
                if (nextTurn != null)
                {
                    currentTurnSide = nextTurn.Side;
                    currentTurnIndex = nextTurn.TurnIndex;
                }
            }
            else
            {
                int maxArgs = GetMaxArgsPerRound(session);
                currentRound = session.DebateRounds.OrderBy(r => r.RoundNumber).FirstOrDefault(r => r.Arguments.Count < maxArgs);

                if (currentRound != null && currentRound.Arguments.Any())
                {
                    var lastSubmittedSide = currentRound.Arguments.Last().Participant.Side;
                    currentTurnSide = lastSubmittedSide == DebateSide.PRO ? DebateSide.CON : DebateSide.PRO;
                }
            }

            return new DebateSessionResponse
            {
                SessionId = session.DebateSessionId,
                Title = session.Topic?.Title ?? "Debate Session",
                Topic = session.Topic?.Description ?? session.Topic?.Title ?? string.Empty,
                EvidenceTopic = MapEvidenceTopic(session.Topic?.Category),
                DebateType = InferDebateType(session),
                Difficulty = session.Difficulty ?? session.Topic?.Difficulty,
                CurrentStage = currentRound != null ? MapRoundTypeToStage(currentRound.RoundType) : DebateStage.Closing,
                CurrentTurnSide = currentTurnSide,
                Status = session.Status,
                CreatedByUserId = session.CreatedBy,
                CreatedAt = session.CreatedAt,
                StartedAt = session.StartTime,
                EndedAt = session.EndTime,
                Participants = session.Participants.Select(p => new ParticipantDto
                {
                    ParticipantId = p.ParticipantId,
                    UserId = p.UserId,
                    SpeakerName = p.ParticipantType == ParticipantType.AI ? "AI Opponent" : (p.User?.FullName ?? "Unknown User"),
                    IsAI = p.ParticipantType == ParticipantType.AI,
                    Side = p.Side,
                    JoinedAt = p.JoinedAt
                }).ToList(),
                CurrentTurn = currentRound == null ? null : new TurnDto
                {
                    TurnId = currentRound.RoundId,
                    Stage = MapRoundTypeToStage(currentRound.RoundType),
                    Side = currentTurnSide,
                    TurnOrder = currentRound.RoundNumber,
                    TurnIndex = currentTurnIndex,
                    TimeLimitSeconds = session.TurnTimeLimitSeconds > 0 ? session.TurnTimeLimitSeconds : (session.Format?.RoundDurationSeconds ?? 180),
                    Status = session.Status == SessionStatus.InProgress ? TurnStatus.Active : TurnStatus.Pending,
                    StartedAt = currentRound.StartTime
                }
            };
        }

        #endregion

        #region 2v2 Side Switching & Swap Requests

        public async Task<ApiResponse<DebateSessionResponse>> SwitchSideAsync(int userId, int sessionId, CancellationToken cancellationToken = default)
        {
            var session = await _debateRepository.GetSessionWithDetailsAsync(sessionId, cancellationToken);
            if (session == null)
            {
                return ApiResponse<DebateSessionResponse>.FailureResponse("Debate session not found.");
            }

            var isCompetition = await _debateRepository.IsSessionInCompetitionAsync(sessionId, cancellationToken);
            if (isCompetition)
            {
                return ApiResponse<DebateSessionResponse>.FailureResponse("Không thể đổi phe trong phiên tranh biện thuộc giải đấu.");
            }

            if (session.Status == SessionStatus.Completed || session.Status == SessionStatus.Cancelled)
            {
                return ApiResponse<DebateSessionResponse>.FailureResponse("Cannot switch sides in a completed or cancelled debate.");
            }

            bool hasArguments = session.DebateRounds.Any(r => r.Arguments.Any());
            if (hasArguments)
            {
                return ApiResponse<DebateSessionResponse>.FailureResponse("Cannot switch sides once the debate has started submitting arguments.");
            }

            var participant = session.Participants.FirstOrDefault(p => p.UserId == userId);
            if (participant == null)
            {
                return ApiResponse<DebateSessionResponse>.FailureResponse("You are not a participant in this debate session.");
            }

            var currentSide = participant.Side;
            var targetSide = (currentSide == DebateSide.PRO || currentSide == DebateSide.Affirmative) ? DebateSide.CON : DebateSide.PRO;

            int maxPerSide = (session.Format?.MaxParticipants > 0 ? session.Format.MaxParticipants : 4) / 2;
            var targetSideCount = session.Participants.Count(p => p.Side == targetSide);
            if (targetSideCount >= maxPerSide)
            {
                return ApiResponse<DebateSessionResponse>.FailureResponse($"Phe đối diện ({targetSide}) đã đủ {maxPerSide} người. Vui lòng gửi yêu cầu tráo phe (swap request) với một người chơi bên phe đó.");
            }

            participant.Side = targetSide;
            await _debateRepository.UpdateParticipantAsync(participant, cancellationToken);

            var updatedSession = await _debateRepository.GetSessionWithDetailsAsync(sessionId, cancellationToken);
            return ApiResponse<DebateSessionResponse>.SuccessResponse(MapToSessionResponse(updatedSession ?? session, userId), $"Đổi phe sang {targetSide} thành công.");
        }

        public async Task<ApiResponse<bool>> SendSwapSideRequestAsync(int userId, int sessionId, SendSwapSideRequest request, CancellationToken cancellationToken = default)
        {
            var session = await _debateRepository.GetSessionWithDetailsAsync(sessionId, cancellationToken);
            if (session == null)
            {
                return ApiResponse<bool>.FailureResponse("Debate session not found.");
            }

            var isCompetition = await _debateRepository.IsSessionInCompetitionAsync(sessionId, cancellationToken);
            if (isCompetition)
            {
                return ApiResponse<bool>.FailureResponse("Không thể đổi phe trong phiên tranh biện thuộc giải đấu.");
            }

            if (session.Status == SessionStatus.Completed || session.Status == SessionStatus.Cancelled)
            {
                return ApiResponse<bool>.FailureResponse("Cannot swap sides in a completed or cancelled debate.");
            }

            bool hasArguments = session.DebateRounds.Any(r => r.Arguments.Any());
            if (hasArguments)
            {
                return ApiResponse<bool>.FailureResponse("Cannot swap sides once the debate has started submitting arguments.");
            }

            if (userId == request.TargetUserId)
            {
                return ApiResponse<bool>.FailureResponse("Cannot send swap request to yourself.");
            }

            var requesterParticipant = session.Participants.FirstOrDefault(p => p.UserId == userId);
            if (requesterParticipant == null)
            {
                return ApiResponse<bool>.FailureResponse("You are not a participant in this debate session.");
            }

            var targetParticipant = session.Participants.FirstOrDefault(p => p.UserId == request.TargetUserId);
            if (targetParticipant == null)
            {
                return ApiResponse<bool>.FailureResponse("Target user is not a participant in this debate session.");
            }

            if (targetParticipant.ParticipantType == ParticipantType.AI)
            {
                return ApiResponse<bool>.FailureResponse("Cannot send swap request to an AI participant.");
            }

            bool isRequesterPro = requesterParticipant.Side == DebateSide.PRO || requesterParticipant.Side == DebateSide.Affirmative;
            bool isTargetPro = targetParticipant.Side == DebateSide.PRO || targetParticipant.Side == DebateSide.Affirmative;

            if (isRequesterPro == isTargetPro)
            {
                return ApiResponse<bool>.FailureResponse("You can only swap sides with a participant on the opposite side.");
            }

            string key = $"{sessionId}_{userId}_{request.TargetUserId}";
            var swapModel = new SideSwapRequestModel
            {
                SessionId = sessionId,
                RequesterUserId = userId,
                RequesterName = requesterParticipant.User?.FullName ?? $"User {userId}",
                RequesterSide = requesterParticipant.Side,
                TargetUserId = request.TargetUserId,
                TargetName = targetParticipant.User?.FullName ?? $"User {request.TargetUserId}",
                TargetSide = targetParticipant.Side,
                CreatedAt = DateTime.UtcNow
            };

            _pendingSwapRequests[key] = swapModel;
            return ApiResponse<bool>.SuccessResponse(true, "Yêu cầu đổi phe đã được gửi tới đối phương. Đang chờ phản hồi.");
        }

        public async Task<ApiResponse<DebateSessionResponse>> RespondSwapSideRequestAsync(int userId, int sessionId, RespondSwapSideRequest request, CancellationToken cancellationToken = default)
        {
            var isCompetition = await _debateRepository.IsSessionInCompetitionAsync(sessionId, cancellationToken);
            if (isCompetition)
            {
                return ApiResponse<DebateSessionResponse>.FailureResponse("Không thể đổi phe trong phiên tranh biện thuộc giải đấu.");
            }

            string key = $"{sessionId}_{request.RequesterUserId}_{userId}";
            if (!_pendingSwapRequests.TryGetValue(key, out var swapModel))
            {
                return ApiResponse<DebateSessionResponse>.FailureResponse("Không tìm thấy yêu cầu đổi phe nào từ người chơi này hoặc yêu cầu đã hết hạn.");
            }

            if ((DateTime.UtcNow - swapModel.CreatedAt).TotalSeconds > 60)
            {
                _pendingSwapRequests.TryRemove(key, out _);
                return ApiResponse<DebateSessionResponse>.FailureResponse("Yêu cầu đổi phe đã hết hạn (quá 60 giây).");
            }

            _pendingSwapRequests.TryRemove(key, out _);

            if (!request.Accept)
            {
                return ApiResponse<DebateSessionResponse>.FailureResponse("Bạn đã từ chối yêu cầu đổi phe.");
            }

            var session = await _debateRepository.GetSessionWithDetailsAsync(sessionId, cancellationToken);
            if (session == null)
            {
                return ApiResponse<DebateSessionResponse>.FailureResponse("Debate session not found.");
            }

            bool hasArguments = session.DebateRounds.Any(r => r.Arguments.Any());
            if (hasArguments)
            {
                return ApiResponse<DebateSessionResponse>.FailureResponse("Cannot swap sides once the debate has started submitting arguments.");
            }

            var requesterParticipant = session.Participants.FirstOrDefault(p => p.UserId == request.RequesterUserId);
            var targetParticipant = session.Participants.FirstOrDefault(p => p.UserId == userId);

            if (requesterParticipant == null || targetParticipant == null)
            {
                return ApiResponse<DebateSessionResponse>.FailureResponse("One of the participants is no longer in this session.");
            }

            using var transaction = await _debateRepository.BeginTransactionAsync(cancellationToken);
            try
            {
                var tempSide = requesterParticipant.Side;
                requesterParticipant.Side = targetParticipant.Side;
                targetParticipant.Side = tempSide;

                await _debateRepository.UpdateParticipantAsync(requesterParticipant, cancellationToken);
                await _debateRepository.UpdateParticipantAsync(targetParticipant, cancellationToken);

                await transaction.CommitAsync(cancellationToken);
            }
            catch
            {
                await transaction.RollbackAsync(cancellationToken);
                throw;
            }

            var updatedSession = await _debateRepository.GetSessionWithDetailsAsync(sessionId, cancellationToken);
            return ApiResponse<DebateSessionResponse>.SuccessResponse(MapToSessionResponse(updatedSession ?? session, userId), "Đổi phe giữa 2 người chơi thành công!");
        }

        public async Task<ApiResponse<List<SideSwapRequestResponse>>> GetPendingSwapRequestsAsync(int userId, int sessionId, CancellationToken cancellationToken = default)
        {
            var isCompetition = await _debateRepository.IsSessionInCompetitionAsync(sessionId, cancellationToken);
            if (isCompetition)
            {
                return ApiResponse<List<SideSwapRequestResponse>>.SuccessResponse(new List<SideSwapRequestResponse>());
            }

            var activeRequests = _pendingSwapRequests.Values
                .Where(r => r.SessionId == sessionId && r.TargetUserId == userId && (DateTime.UtcNow - r.CreatedAt).TotalSeconds <= 60)
                .Select(r => new SideSwapRequestResponse
                {
                    SessionId = r.SessionId,
                    RequesterUserId = r.RequesterUserId,
                    RequesterName = r.RequesterName,
                    RequesterSide = r.RequesterSide.ToString(),
                    TargetUserId = r.TargetUserId,
                    TargetName = r.TargetName,
                    TargetSide = r.TargetSide.ToString(),
                    CreatedAt = r.CreatedAt,
                    ExpiresInSeconds = Math.Max(0, 60 - (int)(DateTime.UtcNow - r.CreatedAt).TotalSeconds)
                })
                .ToList();

            return await Task.FromResult(ApiResponse<List<SideSwapRequestResponse>>.SuccessResponse(activeRequests, "Active swap requests retrieved."));
        }

        public async Task<ApiResponse<DebateSessionResponse>> StartDebateSessionAsync(
            int userId, int sessionId, CancellationToken cancellationToken = default)
        {
            var user = await _userRepository.GetByIdAsync(userId, cancellationToken);
            if (user == null)
            {
                return ApiResponse<DebateSessionResponse>.FailureResponse("User not found.");
            }

            using var transaction = await _debateRepository.BeginTransactionAsync(IsolationLevel.ReadCommitted, cancellationToken);
            try
            {
                // Same lock as leaving: starting a session loaded before a leave would overwrite Cancelled with InProgress.
                await _debateRepository.LockSessionForUpdateAsync(sessionId, cancellationToken);

                var session = await _debateRepository.GetSessionWithDetailsAsync(sessionId, cancellationToken);
                if (session == null)
                {
                    await transaction.RollbackAsync(cancellationToken);
                    return ApiResponse<DebateSessionResponse>.FailureResponse("Debate session not found.");
                }

                // 1. Competition Authorization check vs Standalone check
                var linkedMatch = await _debateRepository.GetLinkedCompetitionMatchAsync(sessionId, cancellationToken);

                if (linkedMatch != null)
                {
                    bool isOrganizer = linkedMatch.Competition.CreatedBy == userId;
                    bool isAssignedJudge = linkedMatch.AssignedJudgeUserId == userId;

                    if (!isOrganizer && !isAssignedJudge)
                    {
                        await transaction.RollbackAsync(cancellationToken);
                        return ApiResponse<DebateSessionResponse>.FailureResponse(
                            "Chỉ Ban tổ chức hoặc Trọng tài được phân công mới có quyền bắt đầu trận đấu giải đấu.");
                    }

                    if (linkedMatch.Status != "Ready")
                    {
                        await transaction.RollbackAsync(cancellationToken);
                        return ApiResponse<DebateSessionResponse>.FailureResponse(
                            $"Trận đấu không ở trạng thái sẵn sàng để bắt đầu (Hiện tại: {linkedMatch.Status}).");
                    }
                }
                else
                {
                    if (session.CreatedBy != userId)
                    {
                        await transaction.RollbackAsync(cancellationToken);
                        return ApiResponse<DebateSessionResponse>.FailureResponse("Chỉ chủ phòng mới có quyền bắt đầu cuộc tranh biện.");
                    }
                }

                if (session.Status != SessionStatus.Waiting)
                {
                    await transaction.RollbackAsync(cancellationToken);
                    return ApiResponse<DebateSessionResponse>.FailureResponse(
                        session.Status == SessionStatus.InProgress
                            ? "Cuộc tranh biện đã bắt đầu từ trước."
                            : $"Không thể bắt đầu cuộc tranh biện đã kết thúc hoặc bị hủy (Trạng thái: {session.Status}).");
                }

                var formatName = session.Format?.FormatName?.ToLower() ?? string.Empty;
                int requiredParticipants = session.Format?.MaxParticipants > 0 ? session.Format.MaxParticipants : 2;
                if (formatName.Contains("2 vs 2") || formatName.Contains("2v2"))
                {
                    requiredParticipants = 4;
                }

                var hasAi = session.Participants.Any(p => p.ParticipantType == ParticipantType.AI);

                // If 2v2 with AI has only 1 human and 2 AI (3 participants), and host starts:
                // automatically backfill the 4th slot with an AI teammate
                if (hasAi && requiredParticipants == 4 && session.Participants.Count == 3)
                {
                    var proCount = session.Participants.Count(p => p.Side == DebateSide.PRO);
                    var emptySide = proCount < 2 ? DebateSide.PRO : DebateSide.CON;

                    var aiTeammate = new DebateParticipant
                    {
                        DebateSessionId = sessionId,
                        UserId = null,
                        ParticipantType = ParticipantType.AI,
                        Side = emptySide,
                        JoinedAt = DateTime.UtcNow
                    };
                    await _debateRepository.AddParticipantAsync(aiTeammate, cancellationToken);
                    session.Participants.Add(aiTeammate);
                }

                if (session.Participants.Count < requiredParticipants)
                {
                    await transaction.RollbackAsync(cancellationToken);
                    return ApiResponse<DebateSessionResponse>.FailureResponse(
                        $"Chưa đủ người tham gia ({session.Participants.Count}/{requiredParticipants}). Vui lòng chờ thêm người chơi tham gia để bắt đầu.");
                }

                if (requiredParticipants == 4)
                {
                    var proCount = session.Participants.Count(p => p.Side == DebateSide.PRO);
                    var conCount = session.Participants.Count(p => p.Side == DebateSide.CON);
                    if (proCount != 2 || conCount != 2)
                    {
                        await transaction.RollbackAsync(cancellationToken);
                        return ApiResponse<DebateSessionResponse>.FailureResponse(
                            $"Hai phe chưa đủ người cân bằng (PRO: {proCount}/2, CON: {conCount}/2).");
                    }
                }
                else if (requiredParticipants == 2)
                {
                    var proCount = session.Participants.Count(p => p.Side == DebateSide.PRO);
                    var conCount = session.Participants.Count(p => p.Side == DebateSide.CON);
                    if (proCount < 1 || conCount < 1)
                    {
                        await transaction.RollbackAsync(cancellationToken);
                        return ApiResponse<DebateSessionResponse>.FailureResponse(
                            $"Cần ít nhất 1 người bên PRO và 1 người bên CON để bắt đầu.");
                    }
                }

                var now = DateTime.UtcNow;
                var claimed = await _debateRepository.ClaimAndStartSessionAsync(
                    sessionId, now, linkedMatch?.CompetitionMatchId, cancellationToken);

                if (!claimed)
                {
                    await transaction.RollbackAsync(cancellationToken);
                    _debateRepository.ClearChangeTracker();
                    return ApiResponse<DebateSessionResponse>.FailureResponse(
                        linkedMatch != null
                            ? "Trận đấu đã được bắt đầu hoặc không còn ở trạng thái sẵn sàng."
                            : "Cuộc tranh biện đã được bắt đầu bởi một tiến trình khác.");
                }

                await transaction.CommitAsync(cancellationToken);

                // ExecuteUpdate bypasses the change tracker, so reload a consistent response.
                _debateRepository.ClearChangeTracker();
                var updatedSession = await _debateRepository.GetSessionWithDetailsAsync(sessionId, cancellationToken);
                return ApiResponse<DebateSessionResponse>.SuccessResponse(MapToSessionResponse(updatedSession!, userId), "Bắt đầu cuộc tranh biện thành công.");
            }
            catch (DbUpdateConcurrencyException)
            {
                await transaction.RollbackAsync(cancellationToken);
                _debateRepository.ClearChangeTracker();
                return ApiResponse<DebateSessionResponse>.FailureResponse("Trận đấu đã được bắt đầu bởi một tiến trình khác.");
            }
            catch (Exception ex)
            {
                await transaction.RollbackAsync(cancellationToken);
                _debateRepository.ClearChangeTracker();
                return ApiResponse<DebateSessionResponse>.FailureResponse($"Lỗi khi bắt đầu cuộc tranh biện: {ex.Message}");
            }
        }

        #endregion

        #region AI Evaluation & Analysis

        public async Task<ApiResponse<DebateEvaluationResponse>> EvaluateSessionAsync(
            int userId, int sessionId, CancellationToken cancellationToken = default)
        {
            if (_aiEvaluatorClient == null)
            {
                return ApiResponse<DebateEvaluationResponse>.FailureResponse("AI Evaluator service is not configured.");
            }

            var user = await _userRepository.GetByIdAsync(userId, cancellationToken);
            if (user == null)
            {
                return ApiResponse<DebateEvaluationResponse>.FailureResponse("User not found.");
            }

            var session = await _debateRepository.GetSessionWithDetailsAsync(sessionId, cancellationToken);
            if (session == null)
            {
                return ApiResponse<DebateEvaluationResponse>.FailureResponse("Debate session not found.");
            }

            bool isParticipant = session.Participants.Any(p => p.UserId == userId);
            bool isCreator = session.CreatedBy == userId;
            var linkedMatch = await _debateRepository.GetLinkedCompetitionMatchAsync(sessionId, cancellationToken);
            bool isMatchJudge = linkedMatch != null && (linkedMatch.AssignedJudgeUserId == userId || linkedMatch.Competition?.CreatedBy == userId);

            if (!isParticipant && !isCreator && !isMatchJudge)
            {
                return ApiResponse<DebateEvaluationResponse>.FailureResponse("You do not have permission to evaluate this debate session.");
            }

            bool hasArguments = session.DebateRounds.Any(r => r.Arguments.Any());
            if (!hasArguments)
            {
                return ApiResponse<DebateEvaluationResponse>.FailureResponse("Debate session has no submitted arguments to evaluate.");
            }

            try
            {
                var evaluation = await GetOrEvaluateSessionAsync(sessionId, cancellationToken);
                return ApiResponse<DebateEvaluationResponse>.SuccessResponse(evaluation, "Debate session evaluated and analyzed successfully.");
            }
            catch (Exception ex)
            {
                _logger?.LogError(ex, "Failed to evaluate debate session {SessionId}", sessionId);
                return ApiResponse<DebateEvaluationResponse>.FailureResponse($"Failed to evaluate debate session: {ex.Message}");
            }
        }

        public async Task<ApiResponse<DebateEvaluationResponse>> GetSessionEvaluationAsync(
            int userId, int sessionId, CancellationToken cancellationToken = default)
        {
            var user = await _userRepository.GetByIdAsync(userId, cancellationToken);
            if (user == null)
            {
                return ApiResponse<DebateEvaluationResponse>.FailureResponse("User not found.");
            }

            var session = await _debateRepository.GetSessionWithDetailsAsync(sessionId, cancellationToken);
            if (session == null)
            {
                return ApiResponse<DebateEvaluationResponse>.FailureResponse("Debate session not found.");
            }

            var existingJudgement = session.AIJudgements.OrderByDescending(j => j.CreatedAt).FirstOrDefault();
            if (existingJudgement != null)
            {
                var response = MapJudgementToResponse(existingJudgement, session);
                return ApiResponse<DebateEvaluationResponse>.SuccessResponse(response, "Evaluation details retrieved.");
            }

            if (session.Status == SessionStatus.Completed && _aiEvaluatorClient != null && session.DebateRounds.Any(r => r.Arguments.Any()))
            {
                return await EvaluateSessionAsync(userId, sessionId, cancellationToken);
            }

            return ApiResponse<DebateEvaluationResponse>.FailureResponse("No evaluation found for this debate session. Please trigger evaluation after the debate.");
        }

        public async Task<ApiResponse<SingleArgumentEvaluationResponse>> EvaluateArgumentAsync(
            int userId, int sessionId, int argumentId, CancellationToken cancellationToken = default)
        {
            if (_aiEvaluatorClient == null)
            {
                return ApiResponse<SingleArgumentEvaluationResponse>.FailureResponse("AI Evaluator service is not configured.");
            }

            var session = await _debateRepository.GetSessionWithDetailsAsync(sessionId, cancellationToken);
            if (session == null)
            {
                return ApiResponse<SingleArgumentEvaluationResponse>.FailureResponse("Debate session not found.");
            }

            var found = session.DebateRounds
                .SelectMany(r => r.Arguments.Select(a => new { Round = r, Argument = a }))
                .FirstOrDefault(x => x.Argument.ArgumentId == argumentId);

            if (found == null)
            {
                return ApiResponse<SingleArgumentEvaluationResponse>.FailureResponse("Argument not found in this debate session.");
            }

            var round = found.Round;
            var arg = found.Argument;
            var participant = arg.Participant;

            var previousArg = round.Arguments
                .Where(a => a.SubmittedAt < arg.SubmittedAt && a.ParticipantId != arg.ParticipantId)
                .OrderByDescending(a => a.SubmittedAt)
                .FirstOrDefault();

            if (previousArg == null)
            {
                var prevRound = session.DebateRounds
                    .Where(r => r.RoundNumber < round.RoundNumber)
                    .OrderByDescending(r => r.RoundNumber)
                    .FirstOrDefault();
                previousArg = prevRound?.Arguments
                    .Where(a => a.Participant.Side != participant.Side)
                    .OrderByDescending(a => a.SubmittedAt)
                    .FirstOrDefault();
            }

            var motion = session.Topic?.Description ?? session.Topic?.Title ?? "Debate motion";
            var sideStr = (participant.Side == DebateSide.PRO || participant.Side == DebateSide.Affirmative) ? "pro" : "con";
            var stageStr = round.RoundType switch
            {
                RoundType.OPENING => "opening",
                RoundType.REBUTTAL => "rebuttal",
                RoundType.CLOSING => "closing",
                _ => "rebuttal"
            };

            var deliveryAnalytics = _argumentDeliveryAnalytics.TryGetValue(arg.ArgumentId, out var storedDa) ? storedDa : null;

            var req = new EvaluateArgumentRequest(
                Motion: motion,
                Side: sideStr,
                Stage: stageStr,
                ArgumentText: arg.Content,
                OpponentArgumentText: previousArg?.Content,
                DeliveryAnalytics: deliveryAnalytics
            );

            try
            {
                var evalResult = await _aiEvaluatorClient.EvaluateArgumentAsync(req, cancellationToken);
                if (evalResult == null)
                {
                    return ApiResponse<SingleArgumentEvaluationResponse>.FailureResponse("AI Evaluator returned an empty response.");
                }

                var response = new SingleArgumentEvaluationResponse
                {
                    ArgumentId = arg.ArgumentId,
                    SessionId = sessionId,
                    RoundNumber = round.RoundNumber,
                    Stage = stageStr,
                    Side = participant.Side.ToString(),
                    SpeakerName = participant.ParticipantType == ParticipantType.AI ? "AI Opponent" : (participant.User?.FullName ?? $"User {participant.UserId}"),
                    OverallScore = evalResult.OverallScore,
                    OverallReasoning = evalResult.OverallReasoning,
                    Criteria = evalResult.Criteria,
                    Strengths = evalResult.Strengths,
                    Weaknesses = evalResult.Weaknesses,
                    Suggestions = evalResult.Suggestions,
                    DeliveryAnalytics = evalResult.DeliveryAnalytics ?? deliveryAnalytics
                };

                return ApiResponse<SingleArgumentEvaluationResponse>.SuccessResponse(response, "Argument evaluated successfully.");
            }
            catch (Exception ex)
            {
                _logger?.LogError(ex, "Failed to evaluate argument {ArgumentId}", argumentId);
                return ApiResponse<SingleArgumentEvaluationResponse>.FailureResponse($"Failed to evaluate argument: {ex.Message}");
            }
        }

        /// <summary>
        /// The ONLY entry point to evaluate a session: returns the stored judgement when there is one, otherwise
        /// evaluates once. Concurrent callers (auto-evaluation of the last turn, GET /evaluation, POST /evaluate) share
        /// the running evaluation, which runs in its own DI scope (see DebateEvaluationCoordinator) and is not cancelled:
        /// <paramref name="cancellationToken"/> only stops this caller from waiting for it.
        /// </summary>
        private Task<DebateEvaluationResponse> GetOrEvaluateSessionAsync(int sessionId, CancellationToken cancellationToken)
        {
            return _evaluationCoordinator.RunOnceAsync(
                sessionId, this, service => service.GetStoredOrEvaluateAsync(sessionId), cancellationToken);
        }

        /// <summary>Auto-evaluation of a debate that just ended: fire and forget, failures are logged.</summary>
        private void StartBackgroundEvaluation(int sessionId)
        {
            _evaluationCoordinator.StartInBackground(
                sessionId, this, service => service.GetStoredOrEvaluateAsync(sessionId), _logger);
        }

        /// <summary>
        /// The topic of a new P2P / 2v2 session: the one picked by id (unknown or inactive → error), otherwise found
        /// or created by its text (no category, so no evidence check).
        /// </summary>
        private async Task<(Topic? Topic, string? Error)> ResolveTopicAsync(
            int? topicId, string title, string description, int userId, CancellationToken cancellationToken)
        {
            if (topicId.HasValue)
            {
                var picked = await _debateRepository.GetTopicByIdAsync(topicId.Value, cancellationToken);
                return picked == null || !picked.IsActive
                    ? (null, "Debate topic not found or no longer active.")
                    : (picked, null);
            }
            var topic = await _debateRepository.GetOrCreateTopicAsync(title.Trim(), description.Trim(), "Medium", userId, cancellationToken);
            return (topic, null);
        }

        /// <summary>Runs inside the coordinator, on the service of the evaluation's own scope.</summary>
        private async Task<DebateEvaluationResponse> GetStoredOrEvaluateAsync(int sessionId)
        {
            var session = await _debateRepository.GetSessionWithDetailsAsync(sessionId, CancellationToken.None)
                ?? throw new InvalidOperationException("Debate session not found.");
            var existing = session.AIJudgements.OrderByDescending(j => j.CreatedAt).FirstOrDefault();
            if (existing != null)
            {
                return MapJudgementToResponse(existing, session);
            }
            return await EvaluateAndStoreSessionInternalAsync(sessionId, CancellationToken.None);
        }

        private static readonly string[] EvaluatedStages = { "opening", "rebuttal", "closing" };

        /// <summary>1-based number of a stage (opening 1, rebuttal 2, closing 3), case-insensitive; 0 if unknown.</summary>
        private static int StageNumber(string? stage)
        {
            return Array.FindIndex(EvaluatedStages, s => string.Equals(s, stage, StringComparison.OrdinalIgnoreCase)) + 1;
        }

        private static List<string> SkippedStages(List<EvaluateRoundResponse> rounds)
        {
            return EvaluatedStages.Where(stage => rounds.All(r => StageNumber(r.Stage) != StageNumber(stage))).ToList();
        }

        private static decimal AverageWithSkipped(List<EvaluateRoundResponse> rounds, List<string> skipped)
        {
            int count = rounds.Count + skipped.Count;
            return rounds.Any() && count > 0 ? rounds.Sum(r => r.RoundScore) / count : 0m;
        }

        private async Task<DebateEvaluationResponse> EvaluateAndStoreSessionInternalAsync(int sessionId, CancellationToken cancellationToken)
        {
            var session = await _debateRepository.GetSessionWithDetailsAsync(sessionId, cancellationToken);
            if (session == null)
            {
                throw new InvalidOperationException("Debate session not found.");
            }

            var motion = session.Topic?.Description ?? session.Topic?.Title ?? "Debate motion";
            var evidenceTopic = MapEvidenceTopic(session.Topic?.Category);
            var sortedRounds = session.DebateRounds.OrderBy(r => r.RoundNumber).ToList();

            // Goi tat ca round (moi round x moi phe) song song; task them theo thu tu round nen ket qua gom lai giu dung thu tu
            var proRoundTasks = new List<Task<EvaluateRoundResponse?>>();
            var conRoundTasks = new List<Task<EvaluateRoundResponse?>>();

            foreach (var round in sortedRounds)
            {
                var roundArgs = round.Arguments.OrderBy(a => a.SubmittedAt).ToList();
                if (!roundArgs.Any()) continue;

                var stageStr = round.RoundType switch
                {
                    RoundType.OPENING => "opening",
                    RoundType.REBUTTAL => "rebuttal",
                    RoundType.CLOSING => "closing",
                    _ => "rebuttal"
                };

                // Formulate turns for PRO evaluation
                var proTurns = roundArgs.Select(a => new RoundTurnDto(
                    Speaker: (a.Participant.Side == DebateSide.PRO || a.Participant.Side == DebateSide.Affirmative) ? "learner" : "opponent",
                    Text: a.Content,
                    DeliveryAnalytics: _argumentDeliveryAnalytics.TryGetValue(a.ArgumentId, out var pDa) ? pDa : null
                )).ToList();

                if (proTurns.Any(t => t.Speaker == "learner"))
                {
                    var proRoundReq = new EvaluateRoundRequest(
                        Motion: motion, Side: "pro", Stage: stageStr, Turns: proTurns, Topic: evidenceTopic,
                        CheckEvidence: !IsAiSide(roundArgs, isPro: true));
                    proRoundTasks.Add(_aiEvaluatorClient!.EvaluateRoundAsync(proRoundReq, cancellationToken));
                }

                // Formulate turns for CON evaluation
                var conTurns = roundArgs.Select(a => new RoundTurnDto(
                    Speaker: (a.Participant.Side == DebateSide.CON || a.Participant.Side == DebateSide.Negative) ? "learner" : "opponent",
                    Text: a.Content,
                    DeliveryAnalytics: _argumentDeliveryAnalytics.TryGetValue(a.ArgumentId, out var cDa) ? cDa : null
                )).ToList();

                if (conTurns.Any(t => t.Speaker == "learner"))
                {
                    var conRoundReq = new EvaluateRoundRequest(
                        Motion: motion, Side: "con", Stage: stageStr, Turns: conTurns, Topic: evidenceTopic,
                        CheckEvidence: !IsAiSide(roundArgs, isPro: false));
                    conRoundTasks.Add(_aiEvaluatorClient!.EvaluateRoundAsync(conRoundReq, cancellationToken));
                }
            }

            // Nhu ban tuan tu: 1 round loi (exception) thi ca lan cham loi, khong luu judgement; response null bi bo qua
            await Task.WhenAll(proRoundTasks.Concat(conRoundTasks));
            var proRounds = proRoundTasks.Select(t => t.Result).OfType<EvaluateRoundResponse>().ToList();
            var conRounds = conRoundTasks.Select(t => t.Result).OfType<EvaluateRoundResponse>().ToList();
            LogUnavailableEvidenceChecks(sessionId, "pro", proRounds);
            LogUnavailableEvidenceChecks(sessionId, "con", conRounds);

            // Stages a side did not speak in count 0 in its overall score (same rule as the FE grading had)
            var proSkipped = SkippedStages(proRounds);
            var conSkipped = SkippedStages(conRounds);

            var proSessionTask = proRounds.Any()
                ? _aiEvaluatorClient!.EvaluateSessionAsync(new EvaluateSessionRequest(Motion: motion, Side: "pro", Rounds: proRounds, SkippedStages: proSkipped), cancellationToken)
                : Task.FromResult<EvaluateSessionResponse?>(null);
            var conSessionTask = conRounds.Any()
                ? _aiEvaluatorClient!.EvaluateSessionAsync(new EvaluateSessionRequest(Motion: motion, Side: "con", Rounds: conRounds, SkippedStages: conSkipped), cancellationToken)
                : Task.FromResult<EvaluateSessionResponse?>(null);
            await Task.WhenAll(proSessionTask, conSessionTask);
            var proSessionRes = proSessionTask.Result;
            var conSessionRes = conSessionTask.Result;

            decimal proScore = proSessionRes?.OverallScore ?? AverageWithSkipped(proRounds, proSkipped);
            decimal conScore = conSessionRes?.OverallScore ?? AverageWithSkipped(conRounds, conSkipped);

            string suggestedWinner;
            if (proScore > conScore) suggestedWinner = "PRO";
            else if (conScore > proScore) suggestedWinner = "CON";
            else suggestedWinner = "TIE";

            var winnerParticipant = session.Participants.FirstOrDefault(p =>
                (suggestedWinner == "PRO" && (p.Side == DebateSide.PRO || p.Side == DebateSide.Affirmative)) ||
                (suggestedWinner == "CON" && (p.Side == DebateSide.CON || p.Side == DebateSide.Negative))
            );

            decimal scoreDiff = Math.Abs(proScore - conScore);
            decimal confidence = Math.Round(Math.Min(1.0m, 0.50m + (scoreDiff / 20.0m)), 2);

            var winnerText = suggestedWinner == "TIE" ? "Kết quả hòa" : $"Phe {suggestedWinner} thắng";
            var summary = $"{winnerText} với điểm số: PRO {proScore:F1}/10 - CON {conScore:F1}/10.";
            var feedback = proSessionRes?.ProgressTrend ?? conSessionRes?.ProgressTrend ?? summary;

            var rawData = new
            {
                ProSession = proSessionRes,
                ConSession = conSessionRes,
                ProRounds = proRounds,
                ConRounds = conRounds
            };
            string rawJson = JsonSerializer.Serialize(rawData);

            var judgement = new AIJudgement
            {
                DebateSessionId = sessionId,
                WinnerParticipantId = winnerParticipant?.ParticipantId,
                SuggestedWinnerSide = suggestedWinner,
                OverallScorePro = proScore,
                OverallScoreCon = conScore,
                OverallScore = Math.Max(proScore, conScore),
                ConfidenceScore = confidence,
                OverallFeedback = feedback,
                Summary = summary,
                AIProvider = "Azure Container Apps - AI Evaluator",
                AIModel = "Groq / Llama-3.3-70b-versatile",
                RawResponseJson = rawJson,
                CreatedAt = DateTime.UtcNow
            };

            await _debateRepository.AddAIJudgementAsync(judgement, cancellationToken);

            judgement.DebateSession = session;
            judgement.WinnerParticipant = winnerParticipant;

            return MapJudgementToResponse(judgement, session);
        }

        private DebateEvaluationResponse MapJudgementToResponse(AIJudgement judgement, DebateSession session)
        {
            var proParticipant = session.Participants.FirstOrDefault(p => p.Side == DebateSide.PRO || p.Side == DebateSide.Affirmative);
            var conParticipant = session.Participants.FirstOrDefault(p => p.Side == DebateSide.CON || p.Side == DebateSide.Negative);
            var winnerParticipant = judgement.WinnerParticipant ?? session.Participants.FirstOrDefault(p => p.ParticipantId == judgement.WinnerParticipantId);

            ParticipantEvaluationDto? proEval = null;
            ParticipantEvaluationDto? conEval = null;

            if (!string.IsNullOrEmpty(judgement.RawResponseJson))
            {
                try
                {
                    using var doc = JsonDocument.Parse(judgement.RawResponseJson);
                    var root = doc.RootElement;

                    if (root.TryGetProperty("ProSession", out var proSessionEl) && proSessionEl.ValueKind == JsonValueKind.Object)
                    {
                        var proSession = JsonSerializer.Deserialize<EvaluateSessionResponse>(proSessionEl.GetRawText());
                        List<EvaluateRoundResponse>? proRounds = null;
                        if (root.TryGetProperty("ProRounds", out var proRoundsEl) && proRoundsEl.ValueKind == JsonValueKind.Array)
                        {
                            proRounds = JsonSerializer.Deserialize<List<EvaluateRoundResponse>>(proRoundsEl.GetRawText());
                        }

                        if (proSession != null)
                        {
                            proEval = new ParticipantEvaluationDto
                            {
                                Side = "PRO",
                                SpeakerName = proParticipant?.ParticipantType == ParticipantType.AI ? "AI Opponent" : (proParticipant?.User?.FullName ?? "User PRO"),
                                OverallScore = proSession.OverallScore,
                                StageBreakdown = proSession.StageBreakdown ?? new(),
                                SkippedStages = proSession.SkippedStages ?? new(),
                                ProgressTrend = proSession.ProgressTrend ?? string.Empty,
                                Strengths = proSession.OverallStrengths ?? new(),
                                Weaknesses = proSession.OverallWeaknesses ?? new(),
                                Suggestions = proSession.OverallSuggestions ?? new(),
                                RoundEvaluations = MapRoundDetails(proRounds)
                            };
                        }
                    }

                    if (root.TryGetProperty("ConSession", out var conSessionEl) && conSessionEl.ValueKind == JsonValueKind.Object)
                    {
                        var conSession = JsonSerializer.Deserialize<EvaluateSessionResponse>(conSessionEl.GetRawText());
                        List<EvaluateRoundResponse>? conRounds = null;
                        if (root.TryGetProperty("ConRounds", out var conRoundsEl) && conRoundsEl.ValueKind == JsonValueKind.Array)
                        {
                            conRounds = JsonSerializer.Deserialize<List<EvaluateRoundResponse>>(conRoundsEl.GetRawText());
                        }

                        if (conSession != null)
                        {
                            conEval = new ParticipantEvaluationDto
                            {
                                Side = "CON",
                                SpeakerName = conParticipant?.ParticipantType == ParticipantType.AI ? "AI Opponent" : (conParticipant?.User?.FullName ?? "User CON"),
                                OverallScore = conSession.OverallScore,
                                StageBreakdown = conSession.StageBreakdown ?? new(),
                                SkippedStages = conSession.SkippedStages ?? new(),
                                ProgressTrend = conSession.ProgressTrend ?? string.Empty,
                                Strengths = conSession.OverallStrengths ?? new(),
                                Weaknesses = conSession.OverallWeaknesses ?? new(),
                                Suggestions = conSession.OverallSuggestions ?? new(),
                                RoundEvaluations = MapRoundDetails(conRounds)
                            };
                        }
                    }
                }
                catch
                {
                    // Fallback to basic summary if JSON parsing has issues
                }
            }

            return new DebateEvaluationResponse
            {
                JudgementId = judgement.JudgementId,
                SessionId = judgement.DebateSessionId,
                SuggestedWinnerSide = judgement.SuggestedWinnerSide ?? "TIE",
                WinnerParticipantId = judgement.WinnerParticipantId,
                WinnerSpeakerName = winnerParticipant?.ParticipantType == ParticipantType.AI ? "AI Opponent" : (winnerParticipant?.User?.FullName ?? (judgement.WinnerParticipantId.HasValue ? $"User {judgement.WinnerParticipantId}" : null)),
                OverallScorePro = judgement.OverallScorePro,
                OverallScoreCon = judgement.OverallScoreCon,
                OverallScore = judgement.OverallScore,
                ConfidenceScore = judgement.ConfidenceScore,
                Summary = judgement.Summary,
                OverallFeedback = judgement.OverallFeedback,
                AIProvider = judgement.AIProvider,
                AIModel = judgement.AIModel,
                EvaluatedAt = judgement.CreatedAt,
                ProEvaluation = proEval,
                ConEvaluation = conEval
            };
        }

        private static readonly HashSet<string> EvidenceTopics = new() { "education", "environment", "technology", "society" };

        // Topic.Category -> chu de kho fact cua AI Evaluator; khac 4 chu de thi null (evaluator khong kiem chung)
        public static string? MapEvidenceTopic(string? category)
        {
            var normalized = category?.Trim().ToLowerInvariant();
            return normalized != null && EvidenceTopics.Contains(normalized) ? normalized : null;
        }

        // Phe dang cham la AI (AI practice) thi khong kiem chung so lieu cua phe do
        private static bool IsAiSide(IEnumerable<Argument> roundArgs, bool isPro)
        {
            var sideArgs = roundArgs.Where(a => isPro
                ? a.Participant.Side == DebateSide.PRO || a.Participant.Side == DebateSide.Affirmative
                : a.Participant.Side == DebateSide.CON || a.Participant.Side == DebateSide.Negative).ToList();
            return sideArgs.Any() && sideArgs.All(a => a.Participant.ParticipantType == ParticipantType.AI);
        }

        // error cua evidence_check chi giu trong RawResponseJson va log, khong tra ve FE
        private void LogUnavailableEvidenceChecks(int sessionId, string side, List<EvaluateRoundResponse> rounds)
        {
            foreach (var round in rounds)
            {
                foreach (var check in round.EvidenceChecks ?? new())
                {
                    if (check?.EvidenceCheck?.Error != null)
                    {
                        _logger?.LogWarning(
                            "Evidence check unavailable for session {SessionId}, side {Side}, stage {Stage}, turn {TurnIndex}: {Error}",
                            sessionId, side, round.Stage, check.TurnIndex, check.EvidenceCheck.Error);
                    }
                }
            }
        }

        private static List<RoundEvaluationDetailDto> MapRoundDetails(List<EvaluateRoundResponse>? rounds)
        {
            return rounds?.Select((r, idx) => new RoundEvaluationDetailDto
            {
                // By stage, not by position: a side that skipped a stage keeps the other rounds' numbers
                RoundNumber = StageNumber(r.Stage) is var stageNumber && stageNumber > 0 ? stageNumber : idx + 1,
                Stage = r.Stage,
                RoundScore = r.RoundScore,
                ConsistencyNote = r.ConsistencyNote,
                Criteria = r.Criteria ?? new(),
                Strengths = r.Strengths ?? new(),
                Weaknesses = r.Weaknesses ?? new(),
                Suggestions = r.Suggestions ?? new(),
                // Judgement cu khong co evidence_checks -> null; turn thieu evidence_check (JSON hong) bi bo qua
                EvidenceChecks = r.EvidenceChecks?.Where(c => c?.EvidenceCheck != null).Select(MapTurnEvidenceCheck).ToList(),
                EvidenceScoreBefore = r.EvidenceScoreBefore,
                EvidenceScoreAfter = r.EvidenceScoreAfter,
                EvidenceRuleApplied = r.EvidenceRuleApplied
            }).ToList() ?? new();
        }

        // Bo field error (chi nam trong RawResponseJson va log)
        private static TurnEvidenceCheckResponse MapTurnEvidenceCheck(TurnEvidenceCheckDto check)
        {
            var summary = check.EvidenceCheck;
            return new TurnEvidenceCheckResponse
            {
                TurnIndex = check.TurnIndex,
                Excerpt = check.Excerpt ?? string.Empty,
                EvidenceCheck = new EvidenceCheckResponse
                {
                    Status = summary.Status ?? string.Empty,
                    Claims = summary.Claims?.Where(c => c != null).Select(c => new EvidenceClaimResponse
                    {
                        Claim = c.Claim ?? string.Empty,
                        Label = c.Label ?? string.Empty,
                        Reason = c.Reason ?? string.Empty,
                        Citations = c.Citations?.Where(f => f != null).Select(f => new EvidenceCitationResponse
                        {
                            FactId = f.FactId ?? string.Empty,
                            Content = f.Content ?? string.Empty,
                            Citation = f.Citation,
                            Stance = f.Stance
                        }).ToList() ?? new()
                    }).ToList() ?? new(),
                    Counts = summary.Counts ?? new(),
                    EvidenceScoreBefore = summary.EvidenceScoreBefore,
                    EvidenceScoreAfter = summary.EvidenceScoreAfter,
                    RuleApplied = summary.RuleApplied ?? string.Empty,
                    Version = summary.Version
                }
            };
        }

        #endregion
    }

    internal class SideSwapRequestModel
    {
        public int SessionId { get; set; }
        public int RequesterUserId { get; set; }
        public string? RequesterName { get; set; }
        public DebateSide RequesterSide { get; set; }
        public int TargetUserId { get; set; }
        public string? TargetName { get; set; }
        public DebateSide TargetSide { get; set; }
        public DateTime CreatedAt { get; set; }
    }
}
