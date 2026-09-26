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
    public class DebateService : IDebateService
    {
        private readonly IDebateRepository _debateRepository;
        private readonly IUserRepository _userRepository;
        private readonly SystemDbContext _context;

        public DebateService(
            IDebateRepository debateRepository,
            IUserRepository userRepository,
            SystemDbContext context)
        {
            _debateRepository = debateRepository;
            _userRepository = userRepository;
            _context = context;
        }

        public async Task<ApiResponse<DebateSessionResponse>> CreateAiPracticeSessionAsync(
            int userId, CreateAiPracticeSessionRequest request, CancellationToken cancellationToken = default)
        {
            var user = await _userRepository.GetByIdAsync(userId, cancellationToken);
            if (user == null)
            {
                return ApiResponse<DebateSessionResponse>.FailureResponse("User not found.");
            }

            var aiSide = request.UserSide == DebateSide.Affirmative ? DebateSide.Negative : DebateSide.Affirmative;

            var session = new DebateSession
            {
                Title = request.Title.Trim(),
                Topic = request.Topic.Trim(),
                DebateType = DebateType.AiPractice,
                Difficulty = request.Difficulty.Trim(),
                CurrentStage = DebateStage.Opening,
                CurrentTurnSide = DebateSide.Affirmative,
                Status = SessionStatus.InProgress,
                CreatedByUserId = userId,
                CreatedAt = DateTime.UtcNow,
                StartedAt = DateTime.UtcNow
            };

            // Add Participants
            session.Participants.Add(new DebateParticipant
            {
                UserId = userId,
                IsAI = false,
                Side = request.UserSide,
                JoinedAt = DateTime.UtcNow
            });

            session.Participants.Add(new DebateParticipant
            {
                UserId = null,
                IsAI = true,
                Side = aiSide,
                JoinedAt = DateTime.UtcNow
            });

            // Initialize Standard 6 Turns
            CreateStandardTurns(session, request.TurnTimeLimitSeconds);

            await _debateRepository.AddSessionAsync(session, cancellationToken);

            var fullSession = await _debateRepository.GetSessionWithDetailsAsync(session.SessionId, cancellationToken);
            return ApiResponse<DebateSessionResponse>.SuccessResponse(MapToSessionResponse(fullSession!, userId), "AI practice debate session created successfully.");
        }

        public async Task<ApiResponse<DebateSessionResponse>> CreateP2pSessionAsync(
            int userId, CreateP2pSessionRequest request, CancellationToken cancellationToken = default)
        {
            var user = await _userRepository.GetByIdAsync(userId, cancellationToken);
            if (user == null)
            {
                return ApiResponse<DebateSessionResponse>.FailureResponse("User not found.");
            }

            var session = new DebateSession
            {
                Title = request.Title.Trim(),
                Topic = request.Topic.Trim(),
                DebateType = DebateType.P2pMatch,
                Difficulty = null,
                CurrentStage = DebateStage.Opening,
                CurrentTurnSide = DebateSide.Affirmative,
                Status = SessionStatus.WaitingForPlayers,
                CreatedByUserId = userId,
                CreatedAt = DateTime.UtcNow
            };

            session.Participants.Add(new DebateParticipant
            {
                UserId = userId,
                IsAI = false,
                Side = request.UserSide,
                JoinedAt = DateTime.UtcNow
            });

            CreateStandardTurns(session, request.TurnTimeLimitSeconds, isP2pPending: true);

            await _debateRepository.AddSessionAsync(session, cancellationToken);

            var fullSession = await _debateRepository.GetSessionWithDetailsAsync(session.SessionId, cancellationToken);
            return ApiResponse<DebateSessionResponse>.SuccessResponse(MapToSessionResponse(fullSession!, userId), "P2P debate session created. Waiting for opponent to join.");
        }

        public async Task<ApiResponse<DebateSessionResponse>> JoinP2pSessionAsync(
            int userId, int sessionId, JoinSessionRequest request, CancellationToken cancellationToken = default)
        {
            var user = await _userRepository.GetByIdAsync(userId, cancellationToken);
            if (user == null)
            {
                return ApiResponse<DebateSessionResponse>.FailureResponse("User not found.");
            }

            var session = await _debateRepository.GetSessionWithDetailsAsync(sessionId, cancellationToken);
            if (session == null)
            {
                return ApiResponse<DebateSessionResponse>.FailureResponse("Debate session not found.");
            }

            if (session.DebateType != DebateType.P2pMatch)
            {
                return ApiResponse<DebateSessionResponse>.FailureResponse("Only P2P Match sessions are open for joining via this endpoint.");
            }

            if (session.Status != SessionStatus.WaitingForPlayers)
            {
                return ApiResponse<DebateSessionResponse>.FailureResponse($"Debate session is not open for joining (Status: {session.Status}).");
            }

            if (session.Participants.Count >= 2)
            {
                return ApiResponse<DebateSessionResponse>.FailureResponse("Debate session is already full.");
            }

            if (session.CreatedByUserId == userId)
            {
                return ApiResponse<DebateSessionResponse>.FailureResponse("Room creator cannot join as the second participant.");
            }

            if (session.Participants.Any(p => p.UserId == userId))
            {
                return ApiResponse<DebateSessionResponse>.FailureResponse("User is already a participant in this session.");
            }

            var existingParticipant = session.Participants.First();
            var assignedSide = existingParticipant.Side == DebateSide.Affirmative ? DebateSide.Negative : DebateSide.Affirmative;

            var newParticipant = new DebateParticipant
            {
                SessionId = sessionId,
                UserId = userId,
                IsAI = false,
                Side = assignedSide,
                JoinedAt = DateTime.UtcNow
            };

            await _debateRepository.AddParticipantAsync(newParticipant, cancellationToken);

            // Start Session and activate Turn 1
            session.Status = SessionStatus.InProgress;
            session.StartedAt = DateTime.UtcNow;

            var firstTurn = session.Turns.FirstOrDefault(t => t.TurnOrder == 1);
            if (firstTurn != null)
            {
                firstTurn.Status = TurnStatus.Active;
                firstTurn.StartedAt = DateTime.UtcNow;
            }

            await _debateRepository.UpdateSessionAsync(session, cancellationToken);

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

            if (session.DebateType == DebateType.Direct1v1)
            {
                if (userId != 0 && !session.Participants.Any(p => p.UserId == userId))
                {
                    return ApiResponse<DebateSessionResponse>.FailureResponse("You are not authorized to view this private 1v1 debate session.");
                }
            }

            return ApiResponse<DebateSessionResponse>.SuccessResponse(MapToSessionResponse(session, userId), "Session details retrieved.");
        }

        public async Task<ApiResponse<DebateSessionResponse>> SubmitArgumentAsync(
            int userId, int sessionId, SubmitArgumentRequest request, CancellationToken cancellationToken = default)
        {
            using var transaction = await _context.Database.BeginTransactionAsync(cancellationToken);
            try
            {
                var session = await _debateRepository.GetSessionWithDetailsAsync(sessionId, cancellationToken);
                if (session == null)
                {
                    return ApiResponse<DebateSessionResponse>.FailureResponse("Debate session not found.");
                }

                if (session.Status != SessionStatus.InProgress)
                {
                    return ApiResponse<DebateSessionResponse>.FailureResponse("Debate session is not currently in progress.");
                }

                var activeTurn = session.Turns.FirstOrDefault(t => t.Status == TurnStatus.Active);
                if (activeTurn == null)
                {
                    return ApiResponse<DebateSessionResponse>.FailureResponse("No active turn found in this session.");
                }

                var participant = session.Participants.FirstOrDefault(p => p.UserId == userId);
                if (participant == null)
                {
                    return ApiResponse<DebateSessionResponse>.FailureResponse("You are not a participant in this debate session.");
                }

                if (participant.Side != activeTurn.Side)
                {
                    return ApiResponse<DebateSessionResponse>.FailureResponse($"It is currently {activeTurn.Side}'s turn to speak.");
                }

                var argument = new DebateArgument
                {
                    TurnId = activeTurn.TurnId,
                    ParticipantId = participant.ParticipantId,
                    Content = request.Content.Trim(),
                    SubmittedAt = DateTime.UtcNow
                };

                await _debateRepository.AddArgumentAsync(argument, cancellationToken);

                // Close active turn
                activeTurn.Status = TurnStatus.Completed;
                activeTurn.EndedAt = DateTime.UtcNow;
                await _debateRepository.UpdateTurnAsync(activeTurn, cancellationToken);

                // Advance to next turn
                var nextTurn = session.Turns.FirstOrDefault(t => t.TurnOrder == activeTurn.TurnOrder + 1);
                if (nextTurn != null)
                {
                    nextTurn.Status = TurnStatus.Active;
                    nextTurn.StartedAt = DateTime.UtcNow;
                    session.CurrentStage = nextTurn.Stage;
                    session.CurrentTurnSide = nextTurn.Side;
                    await _debateRepository.UpdateTurnAsync(nextTurn, cancellationToken);
                }
                else
                {
                    // All 6 turns completed
                    session.Status = SessionStatus.Completed;
                    session.EndedAt = DateTime.UtcNow;
                }

                await _debateRepository.UpdateSessionAsync(session, cancellationToken);
                await transaction.CommitAsync(cancellationToken);

                var updatedSession = await _debateRepository.GetSessionWithDetailsAsync(sessionId, cancellationToken);
                return ApiResponse<DebateSessionResponse>.SuccessResponse(MapToSessionResponse(updatedSession!, userId), "Argument submitted successfully.");
            }
            catch (DbUpdateException)
            {
                await transaction.RollbackAsync(cancellationToken);
                return ApiResponse<DebateSessionResponse>.FailureResponse("An argument for this turn has already been submitted or a concurrent submission occurred.");
            }
            catch (Exception ex)
            {
                await transaction.RollbackAsync(cancellationToken);
                return ApiResponse<DebateSessionResponse>.FailureResponse($"Failed to submit argument: {ex.Message}");
            }
        }

        public async Task<ApiResponse<DebateTranscriptResponse>> GetTranscriptAsync(int userId, int sessionId, CancellationToken cancellationToken = default)
        {
            var session = await _debateRepository.GetSessionWithDetailsAsync(sessionId, cancellationToken);
            if (session == null)
            {
                return ApiResponse<DebateTranscriptResponse>.FailureResponse("Debate session not found.");
            }

            if (session.DebateType == DebateType.Direct1v1)
            {
                if (userId != 0 && !session.Participants.Any(p => p.UserId == userId))
                {
                    return ApiResponse<DebateTranscriptResponse>.FailureResponse("You are not authorized to view this private 1v1 debate transcript.");
                }
            }

            var transcript = new DebateTranscriptResponse
            {
                SessionId = session.SessionId,
                Title = session.Title,
                Topic = session.Topic,
                Status = session.Status,
                Arguments = session.Turns
                    .SelectMany(t => t.Arguments.Select(a => new ArgumentDetailDto
                    {
                        ArgumentId = a.ArgumentId,
                        TurnOrder = t.TurnOrder,
                        Stage = t.Stage,
                        Side = t.Side,
                        SpeakerName = a.Participant.IsAI ? "AI Opponent" : (a.Participant.User?.FullName ?? "Unknown User"),
                        IsAI = a.Participant.IsAI,
                        Content = a.Content,
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
                    SessionId = s.SessionId,
                    Title = s.Title,
                    Topic = s.Topic,
                    DebateType = s.DebateType,
                    Status = s.Status,
                    UserSide = myParticipant?.Side ?? DebateSide.Affirmative,
                    CreatedAt = s.CreatedAt,
                    EndedAt = s.EndedAt
                };
            }).ToList();

            return ApiResponse<List<DebateHistoryItemDto>>.SuccessResponse(history, "User debate history retrieved successfully.");
        }

        #region Helper Methods

        private void CreateStandardTurns(DebateSession session, int turnTimeLimit, bool isP2pPending = false)
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

                bool isActive = (!isP2pPending && turnOrder == 1);

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

        private DebateSessionResponse MapToSessionResponse(DebateSession session, int currentUserId)
        {
            var activeTurn = session.Turns.FirstOrDefault(t => t.Status == TurnStatus.Active);

            return new DebateSessionResponse
            {
                SessionId = session.SessionId,
                Title = session.Title,
                Topic = session.Topic,
                DebateType = session.DebateType,
                Difficulty = session.Difficulty,
                CurrentStage = session.CurrentStage,
                CurrentTurnSide = session.CurrentTurnSide,
                Status = session.Status,
                CreatedByUserId = session.CreatedByUserId,
                CreatedAt = session.CreatedAt,
                StartedAt = session.StartedAt,
                EndedAt = session.EndedAt,
                Participants = session.Participants.Select(p => new ParticipantDto
                {
                    ParticipantId = p.ParticipantId,
                    UserId = p.UserId,
                    SpeakerName = p.IsAI ? "AI Opponent" : (p.User?.FullName ?? "Unknown User"),
                    IsAI = p.IsAI,
                    Side = p.Side,
                    JoinedAt = p.JoinedAt
                }).ToList(),
                CurrentTurn = activeTurn == null ? null : new TurnDto
                {
                    TurnId = activeTurn.TurnId,
                    Stage = activeTurn.Stage,
                    Side = activeTurn.Side,
                    TurnOrder = activeTurn.TurnOrder,
                    TimeLimitSeconds = activeTurn.TimeLimitSeconds,
                    Status = activeTurn.Status,
                    StartedAt = activeTurn.StartedAt
                }
            };
        }

        #endregion
    }
}
