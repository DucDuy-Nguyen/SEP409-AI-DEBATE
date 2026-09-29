using Microsoft.EntityFrameworkCore;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using SystemService.BLL.Common.Responses;
using SystemService.BLL.DTOs.Debate;
using SystemService.BLL.Services.Debate.Interfaces;
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

        public DebateService(
            IDebateRepository debateRepository,
            IUserRepository userRepository)
        {
            _debateRepository = debateRepository;
            _userRepository = userRepository;
        }

        public async Task<ApiResponse<DebateSessionResponse>> CreateAiPracticeSessionAsync(
            int userId, CreateAiPracticeSessionRequest request, CancellationToken cancellationToken = default)
        {
            var user = await _userRepository.GetByIdAsync(userId, cancellationToken);
            if (user == null)
            {
                return ApiResponse<DebateSessionResponse>.FailureResponse("User not found.");
            }

            var topic = await _debateRepository.GetOrCreateTopicAsync(
                request.Title.Trim(), request.Topic.Trim(), request.Difficulty, userId, cancellationToken);

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
                Status = isAi ? SessionStatus.InProgress : SessionStatus.Waiting,
                StartTime = isAi ? DateTime.UtcNow : null,
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
            var message = isAi ? "AI practice debate session created successfully." : "P2P debate session created. Waiting for opponent to join.";
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

            var topic = await _debateRepository.GetOrCreateTopicAsync(
                request.Title.Trim(), request.Topic.Trim(), "Medium", userId, cancellationToken);

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
                Status = isAi ? SessionStatus.InProgress : SessionStatus.Waiting,
                StartTime = isAi ? DateTime.UtcNow : null,
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
            var message = isAi ? "Debate session created with AI opponent." : "P2P debate session created. Waiting for opponent to join.";
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

            var session = await _debateRepository.GetSessionWithDetailsAsync(sessionId, cancellationToken);
            if (session == null)
            {
                return ApiResponse<DebateSessionResponse>.FailureResponse("Debate session not found.");
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

            session.Status = SessionStatus.InProgress;
            session.StartTime = DateTime.UtcNow;

            var firstRound = session.DebateRounds.FirstOrDefault(r => r.RoundNumber == 1);
            if (firstRound != null)
            {
                firstRound.StartTime = DateTime.UtcNow;
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

            return ApiResponse<DebateSessionResponse>.SuccessResponse(MapToSessionResponse(session, userId), "Session details retrieved.");
        }

        public async Task<ApiResponse<DebateSessionResponse>> SubmitArgumentAsync(
            int userId, int sessionId, SubmitArgumentRequest request, CancellationToken cancellationToken = default)
        {
            using var transaction = await _debateRepository.BeginTransactionAsync(cancellationToken);
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

                var participant = session.Participants.FirstOrDefault(p => p.UserId == userId);
                if (participant == null)
                {
                    return ApiResponse<DebateSessionResponse>.FailureResponse("You are not a participant in this debate session.");
                }

                var currentRound = session.DebateRounds
                    .OrderBy(r => r.RoundNumber)
                    .FirstOrDefault(r => r.Arguments.Count < 2);

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
                    var firstSubmittedSide = currentRound.Arguments.First().Participant.Side;
                    expectedTurnSide = firstSubmittedSide == DebateSide.PRO ? DebateSide.CON : DebateSide.PRO;
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

                int durationSeconds = 30;
                if (currentRound.StartTime.HasValue)
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

                if (currentRound.Arguments.Count + 1 >= 2)
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
                        session.Status = SessionStatus.Completed;
                        session.EndTime = DateTime.UtcNow;
                        await _debateRepository.UpdateSessionAsync(session, cancellationToken);
                    }
                }

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
                        SpeakerName = a.Participant.ParticipantType == ParticipantType.AI ? "AI Opponent" : (a.Participant.User?.FullName ?? "Unknown User"),
                        IsAI = a.Participant.ParticipantType == ParticipantType.AI,
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
                    SessionId = s.DebateSessionId,
                    Title = s.Topic?.Title ?? "Debate Session",
                    Topic = s.Topic?.Description ?? s.Topic?.Title ?? string.Empty,
                    DebateType = DebateType.AiPractice,
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

        private DebateSessionResponse MapToSessionResponse(DebateSession session, int currentUserId)
        {
            var currentRound = session.DebateRounds.OrderBy(r => r.RoundNumber).FirstOrDefault(r => r.Arguments.Count < 2);

            var currentTurnSide = DebateSide.PRO;
            if (currentRound != null && currentRound.Arguments.Any())
            {
                var firstArgumentParticipantSide = currentRound.Arguments.First().Participant.Side;
                currentTurnSide = firstArgumentParticipantSide == DebateSide.PRO ? DebateSide.CON : DebateSide.PRO;
            }

            return new DebateSessionResponse
            {
                SessionId = session.DebateSessionId,
                Title = session.Topic?.Title ?? "Debate Session",
                Topic = session.Topic?.Description ?? session.Topic?.Title ?? string.Empty,
                DebateType = DebateType.AiPractice,
                Difficulty = session.Topic?.Difficulty,
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
                    TimeLimitSeconds = session.TurnTimeLimitSeconds > 0 ? session.TurnTimeLimitSeconds : (session.Format?.RoundDurationSeconds ?? 180),
                    Status = TurnStatus.Active,
                    StartedAt = currentRound.StartTime
                }
            };
        }

        #endregion
    }
}
