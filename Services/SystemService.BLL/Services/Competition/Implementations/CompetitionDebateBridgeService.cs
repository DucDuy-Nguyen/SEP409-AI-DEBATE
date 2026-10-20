using System;
using System.Collections.Generic;
using System.Data;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.EntityFrameworkCore;
using SystemService.BLL.Common.Responses;
using SystemService.BLL.DTOs.Debate;
using SystemService.BLL.Services.Competition.Interfaces;
using SystemService.DAL.Context;
using SystemService.DAL.Entities.Competition;
using SystemService.DAL.Entities.Debate;
using SystemService.DAL.Entities.Debate.Enums;
using SystemService.DAL.Repositories.Competition.Interfaces;
using SystemService.DAL.Repositories.Debate.Interfaces;

namespace SystemService.BLL.Services.Competition.Implementations
{
    public class CompetitionDebateBridgeService : ICompetitionDebateBridgeService
    {
        private readonly SystemDbContext _context;
        private readonly IDebateRepository _debateRepository;
        private readonly ICompetitionTeamRepository _teamRepository;

        public CompetitionDebateBridgeService(
            SystemDbContext context,
            IDebateRepository debateRepository,
            ICompetitionTeamRepository teamRepository)
        {
            _context = context;
            _debateRepository = debateRepository;
            _teamRepository = teamRepository;
        }

        public async Task<ApiResponse<DebateSessionResponse>> PrepareMatchDebateAsync(
            int userId, int matchId, int topicId, CancellationToken cancellationToken = default)
        {
            // 1. Fast Path Idempotency & Authority Check (No lock/transaction overhead)
            var matchCheck = await _context.CompetitionMatches
                .AsNoTracking()
                .Include(m => m.Competition)
                .FirstOrDefaultAsync(m => m.CompetitionMatchId == matchId, cancellationToken);

            if (matchCheck == null)
            {
                return ApiResponse<DebateSessionResponse>.FailureResponse("Trận đấu không tồn tại.");
            }

            // Authorization: Only Competition Organizer or Assigned Judge
            if (matchCheck.Competition.CreatedBy != userId && matchCheck.AssignedJudgeUserId != userId)
            {
                return ApiResponse<DebateSessionResponse>.FailureResponse(
                    "Chỉ Ban tổ chức hoặc Trọng tài được phân công mới có quyền chuẩn bị phiên tranh biện cho trận đấu.");
            }

            if (matchCheck.DebateSessionId.HasValue)
            {
                var existingSession = await _debateRepository.GetSessionWithDetailsAsync(
                    matchCheck.DebateSessionId.Value, cancellationToken);
                if (existingSession != null)
                {
                    return ApiResponse<DebateSessionResponse>.SuccessResponse(
                        MapSession(existingSession, userId), "Phiên tranh biện đã tồn tại cho trận đấu này.");
                }
            }

            // 2. Strict Topic Catalog Validation (No synthetic generation, no silent fallbacks)
            var topic = await _context.Topics
                .FirstOrDefaultAsync(t => t.TopicId == topicId && t.IsActive, cancellationToken);

            if (topic == null)
            {
                return ApiResponse<DebateSessionResponse>.FailureResponse(
                    "Chủ đề tranh biện không hợp lệ hoặc chưa được kích hoạt trong hệ thống.");
            }

            // 3. Atomic Preparation Transaction
            using var transaction = await _context.Database.BeginTransactionAsync(
                IsolationLevel.ReadCommitted, cancellationToken);
            try
            {
                var match = await _context.CompetitionMatches
                    .Include(m => m.Competition)
                    .Include(m => m.Participants)
                    .FirstOrDefaultAsync(m => m.CompetitionMatchId == matchId, cancellationToken);

                if (match == null)
                {
                    await transaction.RollbackAsync(cancellationToken);
                    return ApiResponse<DebateSessionResponse>.FailureResponse("Trận đấu không tồn tại.");
                }

                // In-transaction idempotency re-check
                if (match.DebateSessionId.HasValue)
                {
                    await transaction.RollbackAsync(cancellationToken);
                    var existingSession = await _debateRepository.GetSessionWithDetailsAsync(
                        match.DebateSessionId.Value, cancellationToken);
                    return ApiResponse<DebateSessionResponse>.SuccessResponse(
                        MapSession(existingSession!, userId), "Phiên tranh biện đã tồn tại cho trận đấu này.");
                }

                if (match.Status != "Ready")
                {
                    await transaction.RollbackAsync(cancellationToken);
                    return ApiResponse<DebateSessionResponse>.FailureResponse(
                        $"Chỉ có thể chuẩn bị phiên tranh biện khi trận đấu ở trạng thái 'Ready' (Hiện tại: {match.Status}).");
                }

                // 4. Resolve Format
                string formatName = match.Competition.CompetitionType == "TEAM" ? "2 vs 2" : "1 vs 1";
                int maxParticipants = match.Competition.CompetitionType == "TEAM" ? 4 : 2;

                var format = await _context.DebateFormats
                    .FirstOrDefaultAsync(f => f.FormatName.ToLower() == formatName.ToLower() && f.IsActive, cancellationToken)
                    ?? await _debateRepository.GetOrCreateFormatAsync(
                        formatName, maxParticipants, 3, 180, cancellationToken);

                // 5. Construct DebateSession
                var session = new DebateSession
                {
                    TopicId = topic.TopicId,
                    FormatId = format.FormatId,
                    CreatedBy = match.Competition.CreatedBy,
                    TurnTimeLimitSeconds = format.RoundDurationSeconds ?? 180,
                    Status = SessionStatus.Waiting,
                    StartTime = null,
                    CreatedAt = DateTime.UtcNow
                };

                // 6. Map Participants with Fixed PRO/CON Sides
                if (match.Competition.CompetitionType == "INDIVIDUAL")
                {
                    var pro = match.Participants.FirstOrDefault(p => p.Side == "PRO");
                    var con = match.Participants.FirstOrDefault(p => p.Side == "CON");

                    if (pro?.UserId == null || con?.UserId == null)
                    {
                        await transaction.RollbackAsync(cancellationToken);
                        return ApiResponse<DebateSessionResponse>.FailureResponse(
                            "Trận đấu 1v1 thiếu thông tin người tham gia bên PRO hoặc CON.");
                    }

                    session.Participants.Add(new DebateParticipant
                    {
                        UserId = pro.UserId.Value,
                        ParticipantType = ParticipantType.USER,
                        Side = DebateSide.PRO,
                        JoinedAt = DateTime.UtcNow
                    });

                    session.Participants.Add(new DebateParticipant
                    {
                        UserId = con.UserId.Value,
                        ParticipantType = ParticipantType.USER,
                        Side = DebateSide.CON,
                        JoinedAt = DateTime.UtcNow
                    });
                }
                else // TEAM 2v2
                {
                    var proTeamPart = match.Participants.FirstOrDefault(p => p.Side == "PRO");
                    var conTeamPart = match.Participants.FirstOrDefault(p => p.Side == "CON");

                    if (proTeamPart?.TeamId == null || conTeamPart?.TeamId == null)
                    {
                        await transaction.RollbackAsync(cancellationToken);
                        return ApiResponse<DebateSessionResponse>.FailureResponse(
                            "Trận đấu 2v2 thiếu thông tin đội thi đấu bên PRO hoặc CON.");
                    }

                    var proTeam = await _teamRepository.GetWithMembersAsync(proTeamPart.TeamId.Value, cancellationToken);
                    var conTeam = await _teamRepository.GetWithMembersAsync(conTeamPart.TeamId.Value, cancellationToken);

                    if (proTeam == null)
                    {
                        await transaction.RollbackAsync(cancellationToken);
                        return ApiResponse<DebateSessionResponse>.FailureResponse("Không tìm thấy thông tin đội thi đấu bên PRO.");
                    }

                    if (conTeam == null)
                    {
                        await transaction.RollbackAsync(cancellationToken);
                        return ApiResponse<DebateSessionResponse>.FailureResponse("Không tìm thấy thông tin đội thi đấu bên CON.");
                    }

                    // Explicitly combine Captain with Members and enforce exactly two distinct users
                    var proUserIds = new HashSet<int> { proTeam.CaptainUserId };
                    foreach (var member in proTeam.TeamMembers)
                    {
                        proUserIds.Add(member.UserId);
                    }

                    if (proUserIds.Count != 2)
                    {
                        await transaction.RollbackAsync(cancellationToken);
                        return ApiResponse<DebateSessionResponse>.FailureResponse(
                            $"Đội PRO '{proTeam.TeamName}' không đủ điều kiện thi đấu. Đội phải có chính xác 2 thành viên riêng biệt (Bao gồm Đội trưởng và 1 Thành viên). Hiện có: {proUserIds.Count}.");
                    }

                    var conUserIds = new HashSet<int> { conTeam.CaptainUserId };
                    foreach (var member in conTeam.TeamMembers)
                    {
                        conUserIds.Add(member.UserId);
                    }

                    if (conUserIds.Count != 2)
                    {
                        await transaction.RollbackAsync(cancellationToken);
                        return ApiResponse<DebateSessionResponse>.FailureResponse(
                            $"Đội CON '{conTeam.TeamName}' không đủ điều kiện thi đấu. Đội phải có chính xác 2 thành viên riêng biệt (Bao gồm Đội trưởng và 1 Thành viên). Hiện có: {conUserIds.Count}.");
                    }

                    foreach (var uid in proUserIds)
                    {
                        session.Participants.Add(new DebateParticipant
                        {
                            UserId = uid,
                            ParticipantType = ParticipantType.USER,
                            Side = DebateSide.PRO,
                            JoinedAt = DateTime.UtcNow
                        });
                    }

                    foreach (var uid in conUserIds)
                    {
                        session.Participants.Add(new DebateParticipant
                        {
                            UserId = uid,
                            ParticipantType = ParticipantType.USER,
                            Side = DebateSide.CON,
                            JoinedAt = DateTime.UtcNow
                        });
                    }
                }

                // 7. Add 3 Standard DebateRounds
                CreateStandardRounds(session);

                // 8. Atomic Insert & Link
                await _context.DebateSessions.AddAsync(session, cancellationToken);
                await _context.SaveChangesAsync(cancellationToken); // Generates session.DebateSessionId

                match.DebateSessionId = session.DebateSessionId;
                match.UpdatedAt = DateTime.UtcNow;

                await _context.SaveChangesAsync(cancellationToken); // Evaluates RowVersion concurrency token

                await transaction.CommitAsync(cancellationToken);

                var fullSession = await _debateRepository.GetSessionWithDetailsAsync(
                    session.DebateSessionId, cancellationToken);

                return ApiResponse<DebateSessionResponse>.SuccessResponse(
                    MapSession(fullSession!, userId), "Chuẩn bị phiên tranh biện cho trận đấu thành công.");
            }
            catch (DbUpdateConcurrencyException)
            {
                await transaction.RollbackAsync(cancellationToken);
                _context.ChangeTracker.Clear();

                // Concurrency race lost: reload match using AsNoTracking and return the winning session
                var reloaded = await _context.CompetitionMatches
                    .AsNoTracking()
                    .FirstOrDefaultAsync(m => m.CompetitionMatchId == matchId, cancellationToken);

                if (reloaded?.DebateSessionId != null)
                {
                    var wonSession = await _debateRepository.GetSessionWithDetailsAsync(
                        reloaded.DebateSessionId.Value, cancellationToken);
                    if (wonSession != null)
                    {
                        return ApiResponse<DebateSessionResponse>.SuccessResponse(
                            MapSession(wonSession, userId), "Phiên tranh biện đã được tạo thành công bởi tiến trình song song.");
                    }
                }

                return ApiResponse<DebateSessionResponse>.FailureResponse("Xung đột đồng thời khi chuẩn bị phiên tranh biện. Vui lòng thử lại.");
            }
            catch (Exception ex)
            {
                await transaction.RollbackAsync(cancellationToken);
                _context.ChangeTracker.Clear();
                return ApiResponse<DebateSessionResponse>.FailureResponse($"Lỗi khi chuẩn bị phiên tranh biện: {ex.Message}");
            }
        }

        private static void CreateStandardRounds(DebateSession session)
        {
            var roundTypes = new[] { RoundType.OPENING, RoundType.REBUTTAL, RoundType.CLOSING };
            for (int i = 0; i < roundTypes.Length; i++)
            {
                session.DebateRounds.Add(new DebateRound
                {
                    RoundNumber = i + 1,
                    RoundType = roundTypes[i],
                    CreatedAt = DateTime.UtcNow,
                    StartTime = null
                });
            }
        }

        private static DebateSessionResponse MapSession(DebateSession session, int currentUserId)
        {
            var currentRound = session.DebateRounds.FirstOrDefault(r => r.RoundNumber == 1);
            return new DebateSessionResponse
            {
                SessionId = session.DebateSessionId,
                Title = session.Topic?.Title ?? "Competition Match",
                Topic = session.Topic?.Description ?? session.Topic?.Title ?? string.Empty,
                DebateType = DebateType.Competition,
                Difficulty = session.Topic?.Difficulty,
                CurrentStage = DebateStage.Opening,
                CurrentTurnSide = DebateSide.PRO,
                Status = session.Status,
                CreatedByUserId = session.CreatedBy,
                CreatedAt = session.CreatedAt,
                StartedAt = session.StartTime,
                EndedAt = session.EndTime,
                Participants = session.Participants.Select(p => new ParticipantDto
                {
                    ParticipantId = p.ParticipantId,
                    UserId = p.UserId,
                    SpeakerName = p.User?.FullName ?? "Unknown User",
                    IsAI = p.ParticipantType == ParticipantType.AI,
                    Side = p.Side,
                    JoinedAt = p.JoinedAt
                }).ToList(),
                CurrentTurn = currentRound == null ? null : new TurnDto
                {
                    TurnId = currentRound.RoundId,
                    Stage = DebateStage.Opening,
                    Side = DebateSide.PRO,
                    TurnOrder = currentRound.RoundNumber,
                    TimeLimitSeconds = session.TurnTimeLimitSeconds > 0 ? session.TurnTimeLimitSeconds : (session.Format?.RoundDurationSeconds ?? 180),
                    Status = session.Status == SessionStatus.InProgress ? TurnStatus.Active : TurnStatus.Pending,
                    StartedAt = currentRound.StartTime
                }
            };
        }
    }
}
