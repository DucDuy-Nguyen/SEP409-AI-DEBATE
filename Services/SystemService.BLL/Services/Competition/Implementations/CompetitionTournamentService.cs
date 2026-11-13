using System;
using System.Collections.Generic;
using System.Data;
using System.Linq;
using System.Security.Cryptography;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.EntityFrameworkCore;
using SystemService.BLL.Common.Responses;
using SystemService.BLL.DTOs.Competition.Tournament;
using SystemService.BLL.Services.Competition.Interfaces;
using SystemService.DAL.Context;
using SystemService.DAL.Entities.Competition;
using SystemService.DAL.Entities.Debate.Enums;

namespace SystemService.BLL.Services.Competition.Implementations;

public sealed class CompetitionTournamentService : ICompetitionTournamentService
{
    private readonly SystemDbContext _db;
    public CompetitionTournamentService(SystemDbContext db) => _db = db;

    private async Task<SystemService.DAL.Entities.Competition.Competition?> LockCompetitionAsync(int id, CancellationToken ct)
    {
        if (_db.Database.IsSqlServer())
            return await _db.Competitions.FromSqlInterpolated($"SELECT * FROM Competitions WITH (UPDLOCK, HOLDLOCK) WHERE CompetitionId = {id}").SingleOrDefaultAsync(ct);
        return await _db.Competitions.SingleOrDefaultAsync(c => c.CompetitionId == id, ct);
    }

    public async Task<ApiResponse<BracketResponse>> GenerateBracketAsync(int competitionId, int actorId, CancellationToken ct = default)
    {
        await using var tx = await _db.Database.BeginTransactionAsync(IsolationLevel.Serializable, ct);
        var competition = await LockCompetitionAsync(competitionId, ct);
        if (competition == null) return ApiResponse<BracketResponse>.FailureResponse("Competition not found.", CompetitionErrorCodes.NotFound);
        if (competition.CreatedBy != actorId) return ApiResponse<BracketResponse>.FailureResponse("Only the creator may generate the bracket.", CompetitionErrorCodes.Forbidden);
        if (competition.Status != "RegistrationClosed")
            return ApiResponse<BracketResponse>.FailureResponse("Registration must be closed before generating the bracket.", CompetitionErrorCodes.Conflict);
        if (await _db.CompetitionRounds.AnyAsync(r => r.CompetitionId == competitionId, ct)
            || await _db.CompetitionMatches.AnyAsync(m => m.CompetitionId == competitionId, ct))
            return ApiResponse<BracketResponse>.FailureResponse("Bracket already exists.", CompetitionErrorCodes.Conflict);

        var entrants = new List<(int Id, bool Team)>();
        if (competition.CompetitionType == "INDIVIDUAL")
        {
            var registrations = await _db.CompetitionRegistrations.Include(r => r.User)
                .Where(r => r.CompetitionId == competitionId && r.Status == "Approved").ToListAsync(ct);
            if (registrations.Any(r => !r.User.IsActive))
                return ApiResponse<BracketResponse>.FailureResponse("An approved user is inactive.", CompetitionErrorCodes.Conflict);
            entrants.AddRange(registrations.Select(r => (r.UserId, false)));
        }
        else if (competition.CompetitionType == "TEAM")
        {
            var teams = await _db.CompetitionTeams.Include(t => t.Captain)
                .Include(t => t.TeamMembers).ThenInclude(tm => tm.User)
                .Where(t => t.CompetitionId == competitionId && t.Status == "Active").ToListAsync(ct);
            var users = new HashSet<int>();
            foreach (var t in teams)
            {
                if (!t.Captain.IsActive || t.TeamMembers.Count != 1 || !t.TeamMembers.Single().User.IsActive
                    || !users.Add(t.CaptainUserId) || !users.Add(t.TeamMembers.Single().UserId))
                    return ApiResponse<BracketResponse>.FailureResponse("Every active team needs two distinct active users; users may join only one active team.", CompetitionErrorCodes.Conflict);
            }
            entrants.AddRange(teams.Select(t => (t.TeamId, true)));
        }
        else return ApiResponse<BracketResponse>.FailureResponse("Unsupported competition type.");

        if (entrants.Count < 2 || entrants.Select(e => e.Id).Distinct().Count() != entrants.Count
            || (competition.MaxParticipants.HasValue && entrants.Count * (competition.CompetitionType == "TEAM" ? 2 : 1) > competition.MaxParticipants.Value))
            return ApiResponse<BracketResponse>.FailureResponse("Eligible entrants are insufficient, duplicated or above capacity.", CompetitionErrorCodes.Conflict);

        // Draw once; persisted SeedNumber makes the bracket reproducible after commit.
        for (var i = entrants.Count - 1; i > 0; i--)
        {
            var j = RandomNumberGenerator.GetInt32(i + 1);
            (entrants[i], entrants[j]) = (entrants[j], entrants[i]);
        }

        var size = 2;
        while (size < entrants.Count) size *= 2;
        var seeds = SeedSlots(size);
        var rounds = new List<CompetitionRound>();
        var matches = new List<List<CompetitionMatch>>();
        for (int matchCount = size / 2, number = 1; matchCount > 0; matchCount /= 2, number++)
        {
            var round = new CompetitionRound { CompetitionId = competitionId, RoundNumber = number,
                RoundName = matchCount == 1 ? "Final" : $"Round {number}", RoundType = matchCount == 1 ? "FINAL" : null };
            rounds.Add(round);
            var group = Enumerable.Range(1, matchCount).Select(position => new CompetitionMatch
            {
                CompetitionId = competitionId, Round = round, MatchNumber = position,
                BracketPosition = position, Status = "Scheduled"
            }).ToList();
            matches.Add(group);
        }
        _db.CompetitionRounds.AddRange(rounds);
        foreach (var group in matches) _db.CompetitionMatches.AddRange(group);
        await _db.SaveChangesAsync(ct);

        for (var r = 0; r < matches.Count - 1; r++)
            for (var p = 0; p < matches[r].Count; p++)
                matches[r][p].NextMatchId = matches[r + 1][p / 2].CompetitionMatchId;

        for (var slot = 0; slot < seeds.Count; slot++)
        {
            var seed = seeds[slot];
            if (seed > entrants.Count) continue;
            var match = matches[0][slot / 2];
            var e = entrants[seed - 1];
            _db.MatchParticipants.Add(new MatchParticipant { CompetitionMatchId = match.CompetitionMatchId,
                Side = slot % 2 == 0 ? "PRO" : "CON", SeedNumber = seed,
                UserId = e.Team ? null : e.Id, TeamId = e.Team ? e.Id : null });
        }
        await _db.SaveChangesAsync(ct);

        // Exactly one live entrant in a first-round match is an automatic BYE.
        foreach (var match in matches[0])
        {
            var participants = await _db.MatchParticipants.Where(p => p.CompetitionMatchId == match.CompetitionMatchId).ToListAsync(ct);
            if (participants.Count != 1) continue;
            var winner = participants[0];
            winner.IsWinner = true;
            match.Status = "Bye";
            match.CompletedAt = DateTime.UtcNow;
            match.UpdatedAt = match.CompletedAt;
            match.WinnerUserId = winner.UserId;
            match.WinnerTeamId = winner.TeamId;
            var next = matches[1][(match.BracketPosition - 1) / 2];
            _db.MatchParticipants.Add(new MatchParticipant { CompetitionMatchId = next.CompetitionMatchId,
                Side = match.BracketPosition % 2 == 1 ? "PRO" : "CON",
                SeedNumber = winner.SeedNumber, UserId = winner.UserId, TeamId = winner.TeamId });
        }
        await _db.SaveChangesAsync(ct);
        await tx.CommitAsync(ct);
        return await GetBracketAsync(competitionId, ct, actorId);
    }

    public static List<int> SeedSlots(int size)
    {
        var slots = new List<int> { 1, 2 };
        while (slots.Count < size)
        {
            var nextSize = slots.Count * 2 + 1;
            slots = slots.SelectMany(seed => new[] { seed, nextSize - seed }).ToList();
        }
        return slots;
    }

    public async Task<ApiResponse<BracketResponse>> GetBracketAsync(int competitionId, CancellationToken ct = default, int? actorId = null)
    {
        var competition = await _db.Competitions.AsNoTracking().SingleOrDefaultAsync(c => c.CompetitionId == competitionId, ct);
        if (competition == null)
            return ApiResponse<BracketResponse>.FailureResponse("Competition not found.", CompetitionErrorCodes.NotFound);
        if (!await CanViewCompetitionAsync(competition, actorId, ct))
            return ApiResponse<BracketResponse>.FailureResponse("You do not have permission to view this competition.", CompetitionErrorCodes.Forbidden);
        var rounds = await _db.CompetitionRounds.AsNoTracking().Where(r => r.CompetitionId == competitionId)
            .Include(r => r.Matches).ThenInclude(m => m.Participants)
            .Include(r => r.Matches).ThenInclude(m => m.DebateSession)
            .OrderBy(r => r.RoundNumber).ToListAsync(ct);
        var final = rounds.LastOrDefault()?.Matches.SingleOrDefault();
        return ApiResponse<BracketResponse>.SuccessResponse(new BracketResponse(competitionId,
            rounds.Select(r => new RoundResponse(r.RoundNumber, r.Status,
                r.Matches.OrderBy(m => m.BracketPosition).Select(m => new MatchResponse(m.CompetitionMatchId,
                    m.BracketPosition, m.NextMatchId, m.Status,
                    m.Participants.FirstOrDefault(p => p.Side == "PRO")?.UserId,
                    m.Participants.FirstOrDefault(p => p.Side == "PRO")?.TeamId,
                    m.Participants.FirstOrDefault(p => p.Side == "CON")?.UserId,
                    m.Participants.FirstOrDefault(p => p.Side == "CON")?.TeamId,
                    m.WinnerUserId, m.WinnerTeamId, m.DebateSessionId, m.DebateSession?.Status.ToString())).ToList())).ToList(),
            final?.Status == "Completed" ? final.WinnerUserId : null,
            final?.Status == "Completed" ? final.WinnerTeamId : null));
    }

    public async Task<ApiResponse<MatchDetailResponse>> GetMatchDetailAsync(int competitionId, int matchId, int? actorId, CancellationToken ct = default)
    {
        var match = await _db.CompetitionMatches.AsNoTracking()
            .Include(m => m.Competition)
            .Include(m => m.Round)
            .Include(m => m.DebateSession).ThenInclude(s => s!.Topic)
            .Include(m => m.Participants).ThenInclude(p => p.User)
            .Include(m => m.Participants).ThenInclude(p => p.Team).ThenInclude(t => t!.Captain)
            .Include(m => m.Participants).ThenInclude(p => p.Team).ThenInclude(t => t!.TeamMembers).ThenInclude(tm => tm.User)
            .SingleOrDefaultAsync(m => m.CompetitionMatchId == matchId && m.CompetitionId == competitionId, ct);
        if (match == null)
            return ApiResponse<MatchDetailResponse>.FailureResponse("Match not found.", CompetitionErrorCodes.NotFound);
        if (!await CanViewCompetitionAsync(match.Competition, actorId, ct))
            return ApiResponse<MatchDetailResponse>.FailureResponse("You do not have permission to view this competition.", CompetitionErrorCodes.Forbidden);

        return ApiResponse<MatchDetailResponse>.SuccessResponse(new MatchDetailResponse(
            match.CompetitionMatchId,
            match.CompetitionRoundId,
            match.Round.RoundNumber,
            match.BracketPosition,
            match.NextMatchId,
            match.Status,
            match.DebateSession?.Topic == null ? null : new MatchTopicResponse(match.DebateSession.Topic.TopicId, match.DebateSession.Topic.Title),
            match.DebateSession == null ? null : new MatchDebateSessionResponse(match.DebateSessionId!.Value, match.DebateSession.Status.ToString()),
            MapMatchSide(match.Participants.SingleOrDefault(p => p.Side == "PRO")),
            MapMatchSide(match.Participants.SingleOrDefault(p => p.Side == "CON")),
            match.WinnerUserId,
            match.WinnerTeamId));
    }

    private static MatchSideResponse? MapMatchSide(MatchParticipant? participant)
    {
        if (participant == null) return null;
        if (participant.Team != null)
        {
            var teamMembers = new[] { participant.Team.Captain }
                .Concat(participant.Team.TeamMembers.Select(member => member.User))
                .Where(user => user != null)
                .GroupBy(user => user!.UserId)
                .Select(group => group.First()!)
                .OrderBy(user => user.UserId)
                .Select(user => new MatchMemberResponse(user.UserId, user.FullName))
                .ToList();
            return new MatchSideResponse(participant.Side, null, null, participant.TeamId, participant.Team.TeamName, teamMembers);
        }
        var user = participant.User;
        var individualMembers = user == null ? Array.Empty<MatchMemberResponse>() : new[] { new MatchMemberResponse(user.UserId, user.FullName) };
        return new MatchSideResponse(participant.Side, participant.UserId, user?.FullName, null, null, individualMembers);
    }

    private async Task<bool> CanViewCompetitionAsync(SystemService.DAL.Entities.Competition.Competition competition, int? actorId, CancellationToken ct)
    {
        if (competition.IsPublic) return true;
        if (!actorId.HasValue) return false;
        if (competition.CreatedBy == actorId.Value) return true;
        if (await _db.CompetitionRegistrations.AnyAsync(r => r.CompetitionId == competition.CompetitionId && r.UserId == actorId.Value && r.Status == "Approved", ct))
            return true;
        return await _db.CompetitionTeams.AnyAsync(t => t.CompetitionId == competition.CompetitionId && t.Status == "Active"
            && (t.CaptainUserId == actorId.Value || t.TeamMembers.Any(member => member.UserId == actorId.Value)), ct);
    }

    public async Task<ApiResponse<object>> AssignJudgeAsync(int competitionId, int matchId, int actorId, int judgeUserId, CancellationToken ct = default)
    {
        await using var tx = await _db.Database.BeginTransactionAsync(IsolationLevel.Serializable, ct);
        var competition = await LockCompetitionAsync(competitionId, ct);
        if (competition == null) return ApiResponse<object>.FailureResponse("Competition not found.", CompetitionErrorCodes.NotFound);
        if (competition.CreatedBy != actorId) return ApiResponse<object>.FailureResponse("Only the creator may assign a judge.", CompetitionErrorCodes.Forbidden);
        if (competition.Status is not ("RegistrationClosed" or "Ongoing"))
            return ApiResponse<object>.FailureResponse("Judge assignment is unavailable in this competition state.", CompetitionErrorCodes.Conflict);
        var match = await _db.CompetitionMatches.Include(m => m.Participants)
            .SingleOrDefaultAsync(m => m.CompetitionMatchId == matchId && m.CompetitionId == competitionId, ct);
        if (match == null) return ApiResponse<object>.FailureResponse("Match not found.", CompetitionErrorCodes.NotFound);
        if (match.DebateSessionId.HasValue || match.Status is "Bye" or "Completed" or "Cancelled" or "Ongoing" or "Evaluating")
            return ApiResponse<object>.FailureResponse("Judge assignment is closed for this match.", CompetitionErrorCodes.Conflict);
        if (match.Participants.Count != 2)
            return ApiResponse<object>.FailureResponse("Both opponents must be known before judge assignment.", CompetitionErrorCodes.Conflict);
        var judge = await _db.Users.Include(u => u.UserRoles).ThenInclude(ur => ur.Role)
            .SingleOrDefaultAsync(u => u.UserId == judgeUserId, ct);
        if (judge == null || !judge.IsActive || !judge.UserRoles.Any(ur => ur.Role.RoleName is "Lecturer" or "Admin"))
            return ApiResponse<object>.FailureResponse("Judge must be an active Lecturer or Admin.", CompetitionErrorCodes.Conflict);
        if (await IsMatchParticipantAsync(competition, match, judgeUserId, ct))
            return ApiResponse<object>.FailureResponse("Judge cannot score their own match.", CompetitionErrorCodes.Conflict);
        if (!await _db.CompetitionJudges.AnyAsync(j => j.CompetitionId == competitionId && j.UserId == judgeUserId, ct))
            _db.CompetitionJudges.Add(new CompetitionJudge { CompetitionId = competitionId, UserId = judgeUserId });
        match.AssignedJudgeUserId = judgeUserId;
        match.UpdatedAt = DateTime.UtcNow;
        await _db.SaveChangesAsync(ct);
        await tx.CommitAsync(ct);
        return ApiResponse<object>.SuccessResponse(new { match.CompetitionMatchId, match.AssignedJudgeUserId });
    }

    private async Task<bool> IsMatchParticipantAsync(SystemService.DAL.Entities.Competition.Competition competition, CompetitionMatch match, int userId, CancellationToken ct)
    {
        if (competition.CompetitionType == "INDIVIDUAL") return match.Participants.Any(p => p.UserId == userId);
        var teamIds = match.Participants.Where(p => p.TeamId.HasValue).Select(p => p.TeamId!.Value).ToList();
        return await _db.CompetitionTeams.AnyAsync(t => teamIds.Contains(t.TeamId) && t.CaptainUserId == userId, ct)
            || await _db.CompetitionTeamMembers.AnyAsync(tm => teamIds.Contains(tm.TeamId) && tm.UserId == userId, ct);
    }

    public async Task<ApiResponse<MatchReviewResponse>> GetReviewAsync(int competitionId, int matchId, int actorId, CancellationToken ct = default)
    {
        var match = await _db.CompetitionMatches.AsNoTracking().Include(m => m.Participants)
            .SingleOrDefaultAsync(m => m.CompetitionMatchId == matchId && m.CompetitionId == competitionId, ct);
        if (match == null) return ApiResponse<MatchReviewResponse>.FailureResponse("Match not found.", CompetitionErrorCodes.NotFound);
        var competition = await _db.Competitions.AsNoTracking().SingleAsync(c => c.CompetitionId == competitionId, ct);
        if (actorId != competition.CreatedBy)
            return ApiResponse<MatchReviewResponse>.FailureResponse("Only the competition creator may review this match.", CompetitionErrorCodes.Forbidden);
        var ai = match.DebateSessionId.HasValue
            ? await _db.AIJudgements.AsNoTracking().Where(j => j.DebateSessionId == match.DebateSessionId)
                .OrderByDescending(j => j.CreatedAt).FirstOrDefaultAsync(ct) : null;
        var criteria = await _db.DebateCriteria.AsNoTracking().Where(c => c.IsActive).OrderBy(c => c.CriteriaId).ToListAsync(ct);
        return ApiResponse<MatchReviewResponse>.SuccessResponse(new MatchReviewResponse(matchId, match.Status,
            match.AssignedJudgeUserId, match.DebateSessionId, ai?.SuggestedWinnerSide,
            ai?.OverallScorePro, ai?.OverallScoreCon,
            match.Participants.OrderBy(p => p.Side).Select(p => new MatchParticipantReview(p.MatchParticipantId, p.Side, p.UserId, p.TeamId, p.FinalScore)).ToList(),
            criteria.Select(c => new CriterionReview(c.CriteriaId, c.CriteriaName, c.MaxScore, c.Weight)).ToList()));
    }

    public async Task<ApiResponse<object>> FinalizeMatchAsync(int competitionId, int matchId, int actorId, FinalizeMatchRequest request, CancellationToken ct = default)
    {
        await using var tx = await _db.Database.BeginTransactionAsync(IsolationLevel.Serializable, ct);
        var competition = await LockCompetitionAsync(competitionId, ct);
        if (competition == null) return ApiResponse<object>.FailureResponse("Competition not found.", CompetitionErrorCodes.NotFound);
        var match = await _db.CompetitionMatches.Include(m => m.Participants)
            .SingleOrDefaultAsync(m => m.CompetitionMatchId == matchId && m.CompetitionId == competitionId, ct);
        if (match == null) return ApiResponse<object>.FailureResponse("Match not found.", CompetitionErrorCodes.NotFound);
        if (competition.CreatedBy != actorId) return ApiResponse<object>.FailureResponse("Only the competition creator may confirm the result.", CompetitionErrorCodes.Forbidden);
        if (competition.Status != "Ongoing" || match.Status != "Evaluating" || match.Participants.Count != 2 || !match.DebateSessionId.HasValue)
            return ApiResponse<object>.FailureResponse("Match is not ready for official review.", CompetitionErrorCodes.Conflict);
        if (await IsMatchParticipantAsync(competition, match, actorId, ct))
            return ApiResponse<object>.FailureResponse("Judge cannot score their own match.", CompetitionErrorCodes.Forbidden);
        if (!await _db.DebateSessions.AnyAsync(s => s.DebateSessionId == match.DebateSessionId && s.Status == SessionStatus.Completed, ct))
            return ApiResponse<object>.FailureResponse("Debate is not completed.", CompetitionErrorCodes.Conflict);
        if (!await _db.AIJudgements.AnyAsync(j => j.DebateSessionId == match.DebateSessionId, ct))
            return ApiResponse<object>.FailureResponse("AI evaluation is not yet available.", CompetitionErrorCodes.Conflict);
        var criteria = await _db.DebateCriteria.Where(c => c.IsActive).ToListAsync(ct);
        var scores = request?.Scores?.ToList();
        if (criteria.Count == 0 || scores == null || scores.Count != criteria.Count * 2
            || scores.GroupBy(s => (s.MatchParticipantId, s.CriteriaId)).Any(g => g.Count() != 1)
            || scores.Any(s => !match.Participants.Any(p => p.MatchParticipantId == s.MatchParticipantId)
                || s.Score != decimal.Round(s.Score, 2)
                || !criteria.Any(c => c.CriteriaId == s.CriteriaId && s.Score >= 0 && s.Score <= c.MaxScore)))
            return ApiResponse<object>.FailureResponse("Scores must cover each active criterion for both sides within its allowed range.");
        var totals = match.Participants.ToDictionary(p => p.MatchParticipantId,
            p => Math.Round(scores.Where(s => s.MatchParticipantId == p.MatchParticipantId)
                .Sum(s => s.Score * criteria.Single(c => c.CriteriaId == s.CriteriaId).Weight), 2));
        if (totals.Values.Any(v => v > 999.99m))
            return ApiResponse<object>.FailureResponse("Final score exceeds database precision.");
        var winner = match.Participants.SingleOrDefault(p => p.MatchParticipantId == request!.WinnerMatchParticipantId);
        if (winner == null) return ApiResponse<object>.FailureResponse("Winner must be a participant in this match.");
        var other = match.Participants.Single(p => p.MatchParticipantId != winner.MatchParticipantId);
        if (totals[winner.MatchParticipantId] <= totals[other.MatchParticipantId] && string.IsNullOrWhiteSpace(request!.DecisionReason))
            return ApiResponse<object>.FailureResponse("A tie or override requires a decision reason.");
        if (await _db.JudgeScores.AnyAsync(s => s.CompetitionMatchId == matchId, ct))
            return ApiResponse<object>.FailureResponse("This match already has official scores.", CompetitionErrorCodes.Conflict);

        foreach (var input in scores)
            _db.JudgeScores.Add(new JudgeScore { CompetitionMatchId = matchId, JudgeUserId = actorId,
                MatchParticipantId = input.MatchParticipantId, CriteriaId = input.CriteriaId, Score = input.Score,
                Feedback = input.MatchParticipantId == winner.MatchParticipantId && !string.IsNullOrWhiteSpace(request!.DecisionReason)
                    ? $"Decision: {request.DecisionReason.Trim()} | {input.Feedback}" : input.Feedback });
        foreach (var participant in match.Participants)
        {
            participant.FinalScore = totals[participant.MatchParticipantId];
            participant.IsWinner = participant.MatchParticipantId == winner.MatchParticipantId;
        }
        match.WinnerUserId = winner.UserId;
        match.WinnerTeamId = winner.TeamId;
        match.Status = "Completed";
        match.CompletedAt = DateTime.UtcNow;
        match.UpdatedAt = match.CompletedAt;

        if (match.NextMatchId.HasValue)
        {
            var next = await _db.CompetitionMatches.Include(m => m.Participants)
                .SingleOrDefaultAsync(m => m.CompetitionMatchId == match.NextMatchId && m.CompetitionId == competitionId, ct);
            var sourceRound = await _db.CompetitionRounds.SingleAsync(r => r.CompetitionRoundId == match.CompetitionRoundId, ct);
            var targetRound = next == null ? null : await _db.CompetitionRounds.SingleAsync(r => r.CompetitionRoundId == next.CompetitionRoundId, ct);
            if (next == null || targetRound?.RoundNumber != sourceRound.RoundNumber + 1
                || next.BracketPosition != (match.BracketPosition + 1) / 2
                || next.Status != "Scheduled"
                || next.Participants.Any(p => p.Side == (match.BracketPosition % 2 == 1 ? "PRO" : "CON")))
                return ApiResponse<object>.FailureResponse("Next match slot is invalid or occupied.", CompetitionErrorCodes.Conflict);
            next.Participants.Add(new MatchParticipant { Side = match.BracketPosition % 2 == 1 ? "PRO" : "CON",
                UserId = winner.UserId, TeamId = winner.TeamId, SeedNumber = winner.SeedNumber });
            if (next.Participants.Count == 2 && next.Status == "Scheduled") next.Status = "Ready";
            next.UpdatedAt = DateTime.UtcNow;
        }
        else
        {
            var finalRound = await _db.CompetitionRounds.MaxAsync(r => r.CompetitionId == competitionId ? r.RoundNumber : 0, ct);
            var round = await _db.CompetitionRounds.SingleAsync(r => r.CompetitionRoundId == match.CompetitionRoundId, ct);
            if (round.RoundNumber != finalRound)
                return ApiResponse<object>.FailureResponse("Only the final match may determine the champion.", CompetitionErrorCodes.Conflict);
            if (await _db.CompetitionMatches.AnyAsync(m => m.CompetitionId == competitionId
                && m.CompetitionMatchId != matchId && m.Status != "Completed" && m.Status != "Bye", ct)
                || await _db.CompetitionMatches.CountAsync(m => m.CompetitionRoundId == round.CompetitionRoundId, ct) != 1)
                return ApiResponse<object>.FailureResponse("All earlier matches must have official results before completion.", CompetitionErrorCodes.Conflict);
            competition.Status = "Completed";
            competition.UpdatedAt = DateTime.UtcNow;
        }
        await _db.SaveChangesAsync(ct);
        var matchRound = await _db.CompetitionRounds.SingleAsync(r => r.CompetitionRoundId == match.CompetitionRoundId, ct);
        if (!await _db.CompetitionMatches.AnyAsync(m => m.CompetitionRoundId == match.CompetitionRoundId
            && m.Status != "Completed" && m.Status != "Bye", ct))
            matchRound.Status = "Completed";
        if (match.NextMatchId.HasValue)
        {
            var nextRoundId = await _db.CompetitionMatches.Where(m => m.CompetitionMatchId == match.NextMatchId)
                .Select(m => m.CompetitionRoundId).SingleAsync(ct);
            var nextRound = await _db.CompetitionRounds.SingleAsync(r => r.CompetitionRoundId == nextRoundId, ct);
            if (nextRound.Status == "Pending" && await _db.CompetitionMatches.AnyAsync(m => m.CompetitionRoundId == nextRoundId && m.Status == "Ready", ct))
                nextRound.Status = "Ongoing";
        }
        await _db.SaveChangesAsync(ct);
        await tx.CommitAsync(ct);
        return ApiResponse<object>.SuccessResponse(new { match.CompetitionMatchId, match.WinnerUserId, match.WinnerTeamId });
    }
}
