using System.Collections.Concurrent;
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
using SystemService.DAL.Context;
using System.Data;

namespace SystemService.BLL.Services.Debate.Implementations
{
    public class DebateService : IDebateService
    {
        private static readonly ConcurrentDictionary<string, SideSwapRequestModel> _pendingSwapRequests = new();

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

            var session = await _debateRepository.GetSessionWithDetailsAsync(sessionId, cancellationToken);
            if (session == null)
            {
                return ApiResponse<DebateSessionResponse>.FailureResponse("Debate session not found.");
            }

            var isCompetition = await _context.CompetitionMatches
                .AnyAsync(m => m.DebateSessionId == sessionId, cancellationToken);
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

                int maxArgsPerRound = session.Format?.MaxParticipants > 0 ? session.Format.MaxParticipants : 2;

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

                        var linkedMatch = await _context.CompetitionMatches
                            .FirstOrDefaultAsync(m => m.DebateSessionId == sessionId && m.Status == "Ongoing", cancellationToken);
                        if (linkedMatch != null)
                        {
                            linkedMatch.Status = "Evaluating";
                            linkedMatch.UpdatedAt = completedAt;
                        }

                        // UpdateSessionAsync persists both tracked entities inside this transaction.
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

        public async Task<ApiResponse<DebateSessionResponse>> Create2v2SessionAsync(
            int userId, Create2v2SessionRequest request, CancellationToken cancellationToken = default)
        {
            var user = await _userRepository.GetByIdAsync(userId, cancellationToken);
            if (user == null)
            {
                return ApiResponse<DebateSessionResponse>.FailureResponse("User not found.");
            }

            var topic = await _debateRepository.GetOrCreateTopicAsync(
                request.Title.Trim(), request.Topic.Trim(), "Medium", userId, cancellationToken);

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

            var session = await _debateRepository.GetSessionWithDetailsAsync(sessionId, cancellationToken);
            if (session == null)
            {
                return ApiResponse<DebateSessionResponse>.FailureResponse("Debate session not found.");
            }

            var isCompetition = await _context.CompetitionMatches
                .AnyAsync(m => m.DebateSessionId == sessionId, cancellationToken);
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
            int maxArgs = session.Format?.MaxParticipants > 0 ? session.Format.MaxParticipants : 2;
            var currentRound = session.DebateRounds.OrderBy(r => r.RoundNumber).FirstOrDefault(r => r.Arguments.Count < maxArgs);

            var currentTurnSide = DebateSide.PRO;
            if (currentRound != null && currentRound.Arguments.Any())
            {
                var lastSubmittedSide = currentRound.Arguments.Last().Participant.Side;
                currentTurnSide = lastSubmittedSide == DebateSide.PRO ? DebateSide.CON : DebateSide.PRO;
            }

            bool isCompetition = _context.CompetitionMatches.Any(m => m.DebateSessionId == session.DebateSessionId);
            DebateType debateType;
            if (isCompetition)
            {
                debateType = DebateType.Competition;
            }
            else if (session.Participants.Any(p => p.ParticipantType == ParticipantType.AI))
            {
                debateType = DebateType.AiPractice;
            }
            else
            {
                debateType = DebateType.P2pMatch;
            }

            return new DebateSessionResponse
            {
                SessionId = session.DebateSessionId,
                Title = session.Topic?.Title ?? "Debate Session",
                Topic = session.Topic?.Description ?? session.Topic?.Title ?? string.Empty,
                DebateType = debateType,
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

            var isCompetition = await _context.CompetitionMatches
                .AnyAsync(m => m.DebateSessionId == sessionId, cancellationToken);
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

            var isCompetition = await _context.CompetitionMatches
                .AnyAsync(m => m.DebateSessionId == sessionId, cancellationToken);
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
            var isCompetition = await _context.CompetitionMatches
                .AnyAsync(m => m.DebateSessionId == sessionId, cancellationToken);
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
            var isCompetition = await _context.CompetitionMatches
                .AnyAsync(m => m.DebateSessionId == sessionId, cancellationToken);
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

            using var transaction = await _context.Database.BeginTransactionAsync(IsolationLevel.ReadCommitted, cancellationToken);
            try
            {
                var session = await _debateRepository.GetSessionWithDetailsAsync(sessionId, cancellationToken);
                if (session == null)
                {
                    await transaction.RollbackAsync(cancellationToken);
                    return ApiResponse<DebateSessionResponse>.FailureResponse("Debate session not found.");
                }

                // 1. Competition Authorization check vs Standalone check
                var linkedMatch = await _context.CompetitionMatches
                    .Include(m => m.Competition)
                    .FirstOrDefaultAsync(m => m.DebateSessionId == sessionId, cancellationToken);

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

                // Atomically claim the Waiting session. This works for both SQL Server and
                // SQLite and does not require a new concurrency column on DebateSessions.
                var now = DateTime.UtcNow;
                var claimed = await _context.DebateSessions
                    .Where(s => s.DebateSessionId == sessionId && s.Status == SessionStatus.Waiting)
                    .ExecuteUpdateAsync(setters => setters
                        .SetProperty(s => s.Status, SessionStatus.InProgress)
                        .SetProperty(s => s.StartTime, now), cancellationToken);

                if (claimed != 1)
                {
                    await transaction.RollbackAsync(cancellationToken);
                    return ApiResponse<DebateSessionResponse>.FailureResponse(
                        "Cuộc tranh biện đã được bắt đầu bởi một tiến trình khác.");
                }

                var firstRound = session.DebateRounds.FirstOrDefault(r => r.RoundNumber == 1);
                if (firstRound != null)
                {
                    firstRound.StartTime = now;
                }

                if (linkedMatch != null)
                {
                    var matchClaimed = await _context.CompetitionMatches
                        .Where(m => m.CompetitionMatchId == linkedMatch.CompetitionMatchId && m.Status == "Ready")
                        .ExecuteUpdateAsync(setters => setters
                            .SetProperty(m => m.Status, "Ongoing")
                            .SetProperty(m => m.StartedAt, now)
                            .SetProperty(m => m.UpdatedAt, now), cancellationToken);

                    if (matchClaimed != 1)
                    {
                        await transaction.RollbackAsync(cancellationToken);
                        _context.ChangeTracker.Clear();
                        return ApiResponse<DebateSessionResponse>.FailureResponse(
                            "Trận đấu đã được bắt đầu hoặc không còn ở trạng thái sẵn sàng.");
                    }
                }

                await _context.SaveChangesAsync(cancellationToken);
                await transaction.CommitAsync(cancellationToken);

                // ExecuteUpdate bypasses the change tracker, so reload a consistent response.
                _context.ChangeTracker.Clear();
                var updatedSession = await _debateRepository.GetSessionWithDetailsAsync(sessionId, cancellationToken);
                return ApiResponse<DebateSessionResponse>.SuccessResponse(MapToSessionResponse(updatedSession!, userId), "Bắt đầu cuộc tranh biện thành công.");
            }
            catch (DbUpdateConcurrencyException)
            {
                await transaction.RollbackAsync(cancellationToken);
                _context.ChangeTracker.Clear();
                return ApiResponse<DebateSessionResponse>.FailureResponse("Trận đấu đã được bắt đầu bởi một tiến trình khác.");
            }
            catch (Exception ex)
            {
                await transaction.RollbackAsync(cancellationToken);
                _context.ChangeTracker.Clear();
                return ApiResponse<DebateSessionResponse>.FailureResponse($"Lỗi khi bắt đầu cuộc tranh biện: {ex.Message}");
            }
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
