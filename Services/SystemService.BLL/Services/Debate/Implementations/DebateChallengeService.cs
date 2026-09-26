using Microsoft.EntityFrameworkCore;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using SystemService.BLL.Common.Responses;
using SystemService.BLL.DTOs.Debate;
using SystemService.BLL.Services.Debate.Interfaces;
using SystemService.DAL.Context;
using SystemService.DAL.Entities.Debate;
using SystemService.DAL.Entities.Debate.Enums;
using SystemService.DAL.Repositories.Debate.Interfaces;
using SystemService.DAL.Repositories.Identity.Interfaces;

namespace SystemService.BLL.Services.Debate.Implementations
{
    public class DebateChallengeService : IDebateChallengeService
    {
        private readonly IDebateChallengeRepository _challengeRepository;
        private readonly IDebateRepository _debateRepository;
        private readonly IUserRepository _userRepository;
        private readonly SystemDbContext _context;

        public DebateChallengeService(
            IDebateChallengeRepository challengeRepository,
            IDebateRepository debateRepository,
            IUserRepository userRepository,
            SystemDbContext context)
        {
            _challengeRepository = challengeRepository;
            _debateRepository = debateRepository;
            _userRepository = userRepository;
            _context = context;
        }

        public async Task<ApiResponse<ChallengeResponse>> CreateChallengeAsync(
            int challengerUserId, CreateChallengeRequest request, CancellationToken cancellationToken = default)
        {
            if (challengerUserId == request.ChallengedUserId)
            {
                return ApiResponse<ChallengeResponse>.FailureResponse("You cannot challenge yourself.");
            }

            var challenger = await _userRepository.GetByIdAsync(challengerUserId, cancellationToken);
            var challenged = await _userRepository.GetByIdAsync(request.ChallengedUserId, cancellationToken);

            if (challenger == null || challenged == null)
            {
                return ApiResponse<ChallengeResponse>.FailureResponse("Challenger or challenged user not found.");
            }

            var hasPending = await _challengeRepository.HasPendingChallengeBetweenUsersAsync(
                challengerUserId, request.ChallengedUserId, cancellationToken);

            if (hasPending)
            {
                return ApiResponse<ChallengeResponse>.FailureResponse("A pending challenge already exists between these users.");
            }

            var challenge = new DebateChallenge
            {
                ChallengerUserId = challengerUserId,
                ChallengedUserId = request.ChallengedUserId,
                Topic = request.Topic.Trim(),
                ChallengerPreferredSide = request.ChallengerPreferredSide,
                TurnTimeLimitSeconds = request.TurnTimeLimitSeconds,
                Status = ChallengeStatus.Pending,
                CreatedAt = DateTime.UtcNow,
                ExpiresAt = request.ExpiresAt ?? DateTime.UtcNow.AddDays(1)
            };

            await _challengeRepository.AddChallengeAsync(challenge, cancellationToken);

            var fullChallenge = await _challengeRepository.GetChallengeWithDetailsAsync(challenge.ChallengeId, cancellationToken);
            return ApiResponse<ChallengeResponse>.SuccessResponse(MapToChallengeResponse(fullChallenge!), "Challenge sent successfully.");
        }

        public async Task<ApiResponse<List<ChallengeResponse>>> GetReceivedChallengesAsync(int userId, CancellationToken cancellationToken = default)
        {
            var challenges = await _challengeRepository.GetReceivedChallengesAsync(userId, cancellationToken);
            CheckAndUpdateLazyExpirations(challenges);

            var responses = challenges.Select(MapToChallengeResponse).ToList();
            return ApiResponse<List<ChallengeResponse>>.SuccessResponse(responses, "Received challenges retrieved.");
        }

        public async Task<ApiResponse<List<ChallengeResponse>>> GetSentChallengesAsync(int userId, CancellationToken cancellationToken = default)
        {
            var challenges = await _challengeRepository.GetSentChallengesAsync(userId, cancellationToken);
            CheckAndUpdateLazyExpirations(challenges);

            var responses = challenges.Select(MapToChallengeResponse).ToList();
            return ApiResponse<List<ChallengeResponse>>.SuccessResponse(responses, "Sent challenges retrieved.");
        }

        public async Task<ApiResponse<ChallengeResponse>> GetChallengeByIdAsync(int userId, int challengeId, CancellationToken cancellationToken = default)
        {
            var challenge = await _challengeRepository.GetChallengeWithDetailsAsync(challengeId, cancellationToken);
            if (challenge == null)
            {
                return ApiResponse<ChallengeResponse>.FailureResponse("Challenge not found.");
            }

            if (challenge.ChallengerUserId != userId && challenge.ChallengedUserId != userId)
            {
                return ApiResponse<ChallengeResponse>.FailureResponse("You are not authorized to view this challenge.");
            }

            CheckAndUpdateLazyExpiration(challenge);

            return ApiResponse<ChallengeResponse>.SuccessResponse(MapToChallengeResponse(challenge), "Challenge retrieved.");
        }

        public async Task<ApiResponse<ChallengeResponse>> AcceptChallengeAsync(
            int userId, int challengeId, CancellationToken cancellationToken = default)
        {
            using var transaction = await _context.Database.BeginTransactionAsync(cancellationToken);
            try
            {
                var challenge = await _challengeRepository.GetChallengeWithDetailsAsync(challengeId, cancellationToken);
                if (challenge == null)
                {
                    return ApiResponse<ChallengeResponse>.FailureResponse("Challenge not found.");
                }

                if (challenge.ChallengedUserId != userId)
                {
                    return ApiResponse<ChallengeResponse>.FailureResponse("Only the challenged user can accept this challenge.");
                }

                CheckAndUpdateLazyExpiration(challenge);

                if (challenge.Status != ChallengeStatus.Pending)
                {
                    return ApiResponse<ChallengeResponse>.FailureResponse($"Cannot accept challenge because it is currently '{challenge.Status}'.");
                }

                var challengedSide = challenge.ChallengerPreferredSide == DebateSide.Affirmative ? DebateSide.Negative : DebateSide.Affirmative;

                // Create Direct 1v1 DebateSession
                var session = new DebateSession
                {
                    Title = $"1v1 Debate: {challenge.Topic}",
                    Topic = challenge.Topic,
                    DebateType = DebateType.Direct1v1,
                    Difficulty = null,
                    CurrentStage = DebateStage.Opening,
                    CurrentTurnSide = DebateSide.Affirmative,
                    Status = SessionStatus.InProgress,
                    CreatedByUserId = challenge.ChallengerUserId,
                    CreatedAt = DateTime.UtcNow,
                    StartedAt = DateTime.UtcNow
                };

                // Add Participants
                session.Participants.Add(new DebateParticipant
                {
                    UserId = challenge.ChallengerUserId,
                    IsAI = false,
                    Side = challenge.ChallengerPreferredSide,
                    JoinedAt = DateTime.UtcNow
                });

                session.Participants.Add(new DebateParticipant
                {
                    UserId = challenge.ChallengedUserId,
                    IsAI = false,
                    Side = challengedSide,
                    JoinedAt = DateTime.UtcNow
                });

                // Create 6 Standard Turns
                CreateStandardTurns(session, challenge.TurnTimeLimitSeconds);

                await _debateRepository.AddSessionAsync(session, cancellationToken);

                // Update Challenge
                challenge.Status = ChallengeStatus.Accepted;
                challenge.DebateSessionId = session.SessionId;
                challenge.RespondedAt = DateTime.UtcNow;

                await _challengeRepository.UpdateChallengeAsync(challenge, cancellationToken);
                await transaction.CommitAsync(cancellationToken);

                var updatedChallenge = await _challengeRepository.GetChallengeWithDetailsAsync(challengeId, cancellationToken);
                return ApiResponse<ChallengeResponse>.SuccessResponse(MapToChallengeResponse(updatedChallenge!), "Challenge accepted and 1v1 debate session created!");
            }
            catch (Exception ex)
            {
                await transaction.RollbackAsync(cancellationToken);
                return ApiResponse<ChallengeResponse>.FailureResponse($"Failed to accept challenge: {ex.Message}");
            }
        }

        public async Task<ApiResponse<ChallengeResponse>> RejectChallengeAsync(
            int userId, int challengeId, CancellationToken cancellationToken = default)
        {
            var challenge = await _challengeRepository.GetChallengeWithDetailsAsync(challengeId, cancellationToken);
            if (challenge == null)
            {
                return ApiResponse<ChallengeResponse>.FailureResponse("Challenge not found.");
            }

            if (challenge.ChallengedUserId != userId)
            {
                return ApiResponse<ChallengeResponse>.FailureResponse("Only the challenged user can reject this challenge.");
            }

            CheckAndUpdateLazyExpiration(challenge);

            if (challenge.Status != ChallengeStatus.Pending)
            {
                return ApiResponse<ChallengeResponse>.FailureResponse($"Cannot reject challenge because it is currently '{challenge.Status}'.");
            }

            challenge.Status = ChallengeStatus.Rejected;
            challenge.RespondedAt = DateTime.UtcNow;

            await _challengeRepository.UpdateChallengeAsync(challenge, cancellationToken);

            return ApiResponse<ChallengeResponse>.SuccessResponse(MapToChallengeResponse(challenge), "Challenge rejected.");
        }

        public async Task<ApiResponse<ChallengeResponse>> CancelChallengeAsync(
            int userId, int challengeId, CancellationToken cancellationToken = default)
        {
            var challenge = await _challengeRepository.GetChallengeWithDetailsAsync(challengeId, cancellationToken);
            if (challenge == null)
            {
                return ApiResponse<ChallengeResponse>.FailureResponse("Challenge not found.");
            }

            if (challenge.ChallengerUserId != userId)
            {
                return ApiResponse<ChallengeResponse>.FailureResponse("Only the challenger can cancel this challenge.");
            }

            CheckAndUpdateLazyExpiration(challenge);

            if (challenge.Status != ChallengeStatus.Pending)
            {
                return ApiResponse<ChallengeResponse>.FailureResponse($"Cannot cancel challenge because it is currently '{challenge.Status}'.");
            }

            challenge.Status = ChallengeStatus.Cancelled;
            challenge.RespondedAt = DateTime.UtcNow;

            await _challengeRepository.UpdateChallengeAsync(challenge, cancellationToken);

            return ApiResponse<ChallengeResponse>.SuccessResponse(MapToChallengeResponse(challenge), "Challenge cancelled.");
        }

        #region Helpers

        private void CheckAndUpdateLazyExpiration(DebateChallenge challenge)
        {
            if (challenge.Status == ChallengeStatus.Pending && challenge.ExpiresAt.HasValue && challenge.ExpiresAt.Value <= DateTime.UtcNow)
            {
                challenge.Status = ChallengeStatus.Expired;
                _challengeRepository.UpdateChallengeAsync(challenge).Wait();
            }
        }

        private void CheckAndUpdateLazyExpirations(List<DebateChallenge> challenges)
        {
            foreach (var c in challenges)
            {
                CheckAndUpdateLazyExpiration(c);
            }
        }

        private void CreateStandardTurns(DebateSession session, int turnTimeLimit)
        {
            var turnSequence = new List<(DebateStage Stage, DebateSide Side)>
            {
                (DebateStage.Opening, DebateSide.Affirmative),
                (DebateStage.Opening, DebateSide.Negative),
                (DebateStage.Rebuttal, DebateSide.Affirmative),
                (DebateStage.Rebuttal, DebateSide.Negative),
                (DebateStage.Closing, DebateSide.Affirmative),
                (DebateStage.Closing, DebateSide.Negative)
            };

            for (int i = 0; i < turnSequence.Count; i++)
            {
                int turnOrder = i + 1;
                var (stage, side) = turnSequence[i];
                bool isActive = (turnOrder == 1);

                session.Turns.Add(new DebateTurn
                {
                    Stage = stage,
                    Side = side,
                    TurnOrder = turnOrder,
                    TimeLimitSeconds = turnTimeLimit,
                    Status = isActive ? TurnStatus.Active : TurnStatus.Pending,
                    StartedAt = isActive ? DateTime.UtcNow : null
                });
            }
        }

        private ChallengeResponse MapToChallengeResponse(DebateChallenge c)
        {
            return new ChallengeResponse
            {
                ChallengeId = c.ChallengeId,
                Challenger = new ChallengeUserSummaryDto
                {
                    UserId = c.ChallengerUserId,
                    FullName = c.ChallengerUser?.FullName ?? "User " + c.ChallengerUserId,
                    Email = c.ChallengerUser?.Email ?? string.Empty
                },
                Challenged = new ChallengeUserSummaryDto
                {
                    UserId = c.ChallengedUserId,
                    FullName = c.ChallengedUser?.FullName ?? "User " + c.ChallengedUserId,
                    Email = c.ChallengedUser?.Email ?? string.Empty
                },
                Topic = c.Topic,
                ChallengerPreferredSide = c.ChallengerPreferredSide,
                TurnTimeLimitSeconds = c.TurnTimeLimitSeconds,
                Status = c.Status,
                DebateSessionId = c.DebateSessionId,
                CreatedAt = c.CreatedAt,
                RespondedAt = c.RespondedAt,
                ExpiresAt = c.ExpiresAt
            };
        }

        #endregion
    }
}
