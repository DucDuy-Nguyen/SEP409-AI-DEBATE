using System;
using System.Collections.Generic;

namespace SystemService.BLL.DTOs.Competition.Tournament;

public sealed record BracketResponse(int CompetitionId, IReadOnlyList<RoundResponse> Rounds, int? ChampionUserId, int? ChampionTeamId);
public sealed record RoundResponse(int RoundNumber, string Status, IReadOnlyList<MatchResponse> Matches);
public sealed record MatchResponse(int MatchId, int BracketPosition, int? NextMatchId, string Status, int? ProUserId, int? ProTeamId, int? ConUserId, int? ConTeamId, int? WinnerUserId, int? WinnerTeamId);
public sealed record ScoreInput(long MatchParticipantId, int CriteriaId, decimal Score, string? Feedback);
public sealed record AssignJudgeRequest(int JudgeUserId);
public sealed record FinalizeMatchRequest(IReadOnlyList<ScoreInput> Scores, long WinnerMatchParticipantId, string? DecisionReason);
public sealed record MatchReviewResponse(int MatchId, string Status, int? AssignedJudgeUserId, int? DebateSessionId, string? AiSuggestedWinnerSide, decimal? AiScorePro, decimal? AiScoreCon, IReadOnlyList<MatchParticipantReview> Participants, IReadOnlyList<CriterionReview> Criteria);
public sealed record MatchParticipantReview(long MatchParticipantId, string Side, int? UserId, int? TeamId, decimal? FinalScore);
public sealed record CriterionReview(int CriteriaId, string Name, decimal MaxScore, decimal Weight);
