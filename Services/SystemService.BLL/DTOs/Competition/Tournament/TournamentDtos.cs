using System;
using System.Collections.Generic;
using System.Text.Json.Serialization;

namespace SystemService.BLL.DTOs.Competition.Tournament;

public sealed record BracketResponse(int CompetitionId, IReadOnlyList<RoundResponse> Rounds, int? ChampionUserId, int? ChampionTeamId);
public sealed record RoundResponse(int RoundNumber, string Status, IReadOnlyList<MatchResponse> Matches);
public sealed record MatchResponse(int MatchId, int BracketPosition, int? NextMatchId, string Status, int? ProUserId, int? ProTeamId, int? ConUserId, int? ConTeamId, int? WinnerUserId, int? WinnerTeamId, int? DebateSessionId = null, string? DebateSessionStatus = null);
public sealed record MatchDetailResponse(
    int MatchId,
    int RoundId,
    int RoundNumber,
    int BracketPosition,
    int? NextMatchId,
    string Status,
    MatchTopicResponse? Topic,
    MatchDebateSessionResponse? DebateSession,
    MatchSideResponse? ProSide,
    MatchSideResponse? ConSide,
    int? WinnerUserId,
    int? WinnerTeamId);
public sealed record MatchTopicResponse(int TopicId, string Title);
public sealed record MatchDebateSessionResponse(int DebateSessionId, string Status);
public sealed record MatchSideResponse(string Side, int? UserId, string? DisplayName, int? TeamId, string? TeamName, IReadOnlyList<MatchMemberResponse> Members);
public sealed record MatchMemberResponse(int UserId, string DisplayName);
public sealed record AssignJudgeRequest(int JudgeUserId);

// Legacy ScoreInput for backward compatibility
public sealed record ScoreInput(long MatchParticipantId, int CriteriaId, decimal Score, string? Feedback);

// Phase 3 Per-round Score Input
public sealed record RoundScoreInput(
    int? RoundId,
    long MatchParticipantId,
    int CriteriaId,
    decimal Score,
    string? Feedback = null
);

public sealed record RoundRubricReviewDto(
    int RoundId,
    int RoundNumber,
    string Stage,
    long MatchParticipantId,
    string Side,
    int CriteriaId,
    string CriterionCode,
    string CriteriaName,
    decimal AiScore,
    string? AiFeedback
);

public sealed record MatchParticipantReview(
    long MatchParticipantId,
    string Side,
    int? UserId,
    int? TeamId,
    decimal? FinalScore,
    string? DisplayName = null,
    string? TeamName = null,
    bool IsWinner = false
);

public sealed record CriterionReview(
    int CriteriaId,
    string Name,
    decimal MaxScore,
    decimal Weight,
    string? CriterionCode = null
);

public sealed record MatchReviewResponse(
    int MatchId,
    string Status,
    int? AssignedJudgeUserId,
    int? DebateSessionId,
    string? AiSuggestedWinnerSide,
    decimal? AiScorePro,
    decimal? AiScoreCon,
    IReadOnlyList<MatchParticipantReview> Participants,
    IReadOnlyList<CriterionReview> Criteria,
    string EvaluationStatus = "Pending",
    string? EvaluationError = null,
    string? AiSummary = null,
    string? AiOverallFeedback = null,
    decimal? AiConfidenceScore = null,
    IReadOnlyList<RoundRubricReviewDto>? RoundRubrics = null,
    string? DecisionType = null,
    string? DecisionReason = null,
    int? FinalizedByUserId = null
);

public sealed class FinalizeMatchRequest
{
    public string DecisionType { get; init; } = "ACCEPT";
    public string? DecisionReason { get; init; }
    public IReadOnlyList<RoundScoreInput>? Scores { get; init; }
    public long? WinnerMatchParticipantId { get; init; }
    public IReadOnlyList<ScoreInput>? LegacyScores { get; init; }

    public FinalizeMatchRequest() { }

    [JsonConstructor]
    public FinalizeMatchRequest(
        string? decisionType = null,
        string? decisionReason = null,
        IReadOnlyList<RoundScoreInput>? scores = null,
        long? winnerMatchParticipantId = null)
    {
        DecisionType = decisionType ?? "ACCEPT";
        DecisionReason = decisionReason;
        Scores = scores;
        WinnerMatchParticipantId = winnerMatchParticipantId;
    }

    // Legacy constructor for existing integration tests
    public FinalizeMatchRequest(
        IReadOnlyList<ScoreInput> legacyScores,
        long winnerMatchParticipantId,
        string? decisionReason)
    {
        DecisionType = "OVERRIDE";
        WinnerMatchParticipantId = winnerMatchParticipantId;
        DecisionReason = decisionReason;
        LegacyScores = legacyScores;
    }
}
