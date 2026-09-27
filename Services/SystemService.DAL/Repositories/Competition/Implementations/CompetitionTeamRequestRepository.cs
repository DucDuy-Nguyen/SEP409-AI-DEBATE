using Microsoft.EntityFrameworkCore;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using SystemService.DAL.Context;
using SystemService.DAL.Entities.Competition;
using SystemService.DAL.Repositories.Competition.Interfaces;

namespace SystemService.DAL.Repositories.Competition.Implementations
{
    public class CompetitionTeamRequestRepository : ICompetitionTeamRequestRepository
    {
        private readonly SystemDbContext _context;

        public CompetitionTeamRequestRepository(SystemDbContext context)
        {
            _context = context;
        }

        public async Task<CompetitionTeamRequest?> GetByIdAsync(long requestId, CancellationToken cancellationToken = default)
        {
            return await _context.CompetitionTeamRequests
                .Include(r => r.Team)
                .Include(r => r.User)
                .Include(r => r.Creator)
                .Include(r => r.Responder)
                .FirstOrDefaultAsync(r => r.RequestId == requestId, cancellationToken);
        }

        public async Task<bool> HasPendingRequestAsync(int teamId, int userId, CancellationToken cancellationToken = default)
        {
            return await _context.CompetitionTeamRequests
                .AnyAsync(r => r.TeamId == teamId && r.UserId == userId && r.Status == "Pending", cancellationToken);
        }

        public async Task<List<CompetitionTeamRequest>> GetMyPendingInvitationsAsync(int competitionId, int userId, CancellationToken cancellationToken = default)
        {
            return await _context.CompetitionTeamRequests
                .Include(r => r.Team)
                .Include(r => r.Creator)
                .Where(r => r.Team.CompetitionId == competitionId && r.UserId == userId && r.RequestType == "Invitation" && r.Status == "Pending")
                .OrderByDescending(r => r.CreatedAt)
                .ToListAsync(cancellationToken);
        }

        public async Task<List<CompetitionTeamRequest>> GetTeamJoinRequestsAsync(int teamId, CancellationToken cancellationToken = default)
        {
            return await _context.CompetitionTeamRequests
                .Include(r => r.User)
                .Where(r => r.TeamId == teamId && r.RequestType == "JoinRequest" && r.Status == "Pending")
                .OrderByDescending(r => r.CreatedAt)
                .ToListAsync(cancellationToken);
        }

        public async Task AddRequestAsync(CompetitionTeamRequest request, CancellationToken cancellationToken = default)
        {
            await _context.CompetitionTeamRequests.AddAsync(request, cancellationToken);
            await _context.SaveChangesAsync(cancellationToken);
        }

        public async Task UpdateRequestAsync(CompetitionTeamRequest request, CancellationToken cancellationToken = default)
        {
            _context.CompetitionTeamRequests.Update(request);
            await _context.SaveChangesAsync(cancellationToken);
        }

        public async Task AcceptInvitationWithMemberAsync(CompetitionTeamRequest request, CompetitionTeamMember member, int competitionId, int userId, CancellationToken cancellationToken = default)
        {
            using var transaction = await _context.Database.BeginTransactionAsync(cancellationToken);
            try
            {
                await _context.CompetitionTeamMembers.AddAsync(member, cancellationToken);

                request.Status = "Accepted";
                request.RespondedAt = DateTime.UtcNow;
                request.RespondedByUserId = userId;
                _context.CompetitionTeamRequests.Update(request);

                var otherPendingRequests = await _context.CompetitionTeamRequests
                    .Include(r => r.Team)
                    .Where(r => r.UserId == userId && r.Status == "Pending" && r.Team.CompetitionId == competitionId && r.RequestId != request.RequestId)
                    .ToListAsync(cancellationToken);

                foreach (var other in otherPendingRequests)
                {
                    other.Status = "Cancelled";
                    other.RespondedAt = DateTime.UtcNow;
                    other.RespondedByUserId = userId;
                    _context.CompetitionTeamRequests.Update(other);
                }

                await _context.SaveChangesAsync(cancellationToken);
                await transaction.CommitAsync(cancellationToken);
            }
            catch
            {
                await transaction.RollbackAsync(cancellationToken);
                throw;
            }
        }

        public async Task ApproveJoinRequestWithMemberAsync(CompetitionTeamRequest request, CompetitionTeamMember member, int competitionId, int userId, int captainUserId, CancellationToken cancellationToken = default)
        {
            using var transaction = await _context.Database.BeginTransactionAsync(cancellationToken);
            try
            {
                await _context.CompetitionTeamMembers.AddAsync(member, cancellationToken);

                request.Status = "Accepted";
                request.RespondedAt = DateTime.UtcNow;
                request.RespondedByUserId = captainUserId;
                _context.CompetitionTeamRequests.Update(request);

                var otherPendingRequests = await _context.CompetitionTeamRequests
                    .Include(r => r.Team)
                    .Where(r => r.UserId == userId && r.Status == "Pending" && r.Team.CompetitionId == competitionId && r.RequestId != request.RequestId)
                    .ToListAsync(cancellationToken);

                foreach (var other in otherPendingRequests)
                {
                    other.Status = "Cancelled";
                    other.RespondedAt = DateTime.UtcNow;
                    other.RespondedByUserId = captainUserId;
                    _context.CompetitionTeamRequests.Update(other);
                }

                await _context.SaveChangesAsync(cancellationToken);
                await transaction.CommitAsync(cancellationToken);
            }
            catch
            {
                await transaction.RollbackAsync(cancellationToken);
                throw;
            }
        }
    }
}
