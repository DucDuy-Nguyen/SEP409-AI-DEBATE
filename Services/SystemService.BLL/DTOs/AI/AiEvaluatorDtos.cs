using System.Collections.Generic;
using System.Text.Json.Serialization;

namespace SystemService.BLL.DTOs.AI
{
    public record EvaluateArgumentRequest(
        [property: JsonPropertyName("motion")] string Motion,
        [property: JsonPropertyName("side")] string Side,
        [property: JsonPropertyName("stage")] string Stage,
        [property: JsonPropertyName("argument_text")] string ArgumentText,
        [property: JsonPropertyName("opponent_argument_text")] string? OpponentArgumentText = null
    );

    public record CriterionScoreDto(
        [property: JsonPropertyName("name")] string Name,
        [property: JsonPropertyName("score")] int Score,
        [property: JsonPropertyName("reasoning")] string Reasoning
    );

    public record EvaluateArgumentResponse(
        [property: JsonPropertyName("overall_score")] decimal OverallScore,
        [property: JsonPropertyName("overall_reasoning")] string OverallReasoning,
        [property: JsonPropertyName("criteria")] List<CriterionScoreDto> Criteria,
        [property: JsonPropertyName("strengths")] List<string> Strengths,
        [property: JsonPropertyName("weaknesses")] List<string> Weaknesses,
        [property: JsonPropertyName("suggestions")] List<string> Suggestions,
        [property: JsonPropertyName("raw_model_output")] string? RawModelOutput
    );

    public record RoundTurnDto(
        [property: JsonPropertyName("speaker")] string Speaker,
        [property: JsonPropertyName("text")] string Text
    );

    public record EvaluateRoundRequest(
        [property: JsonPropertyName("motion")] string Motion,
        [property: JsonPropertyName("side")] string Side,
        [property: JsonPropertyName("stage")] string Stage,
        [property: JsonPropertyName("turns")] List<RoundTurnDto> Turns
    );

    public record EvaluateRoundResponse(
        [property: JsonPropertyName("stage")] string Stage,
        [property: JsonPropertyName("round_score")] decimal RoundScore,
        [property: JsonPropertyName("criteria")] List<CriterionScoreDto> Criteria,
        [property: JsonPropertyName("consistency_note")] string ConsistencyNote,
        [property: JsonPropertyName("strengths")] List<string> Strengths,
        [property: JsonPropertyName("weaknesses")] List<string> Weaknesses,
        [property: JsonPropertyName("suggestions")] List<string> Suggestions
    );

    public record EvaluateSessionRequest(
        [property: JsonPropertyName("motion")] string Motion,
        [property: JsonPropertyName("side")] string Side,
        [property: JsonPropertyName("rounds")] List<EvaluateRoundResponse> Rounds
    );

    public record EvaluateSessionResponse(
        [property: JsonPropertyName("overall_score")] decimal OverallScore,
        [property: JsonPropertyName("stage_breakdown")] Dictionary<string, decimal> StageBreakdown,
        [property: JsonPropertyName("progress_trend")] string ProgressTrend,
        [property: JsonPropertyName("overall_strengths")] List<string> OverallStrengths,
        [property: JsonPropertyName("overall_weaknesses")] List<string> OverallWeaknesses,
        [property: JsonPropertyName("overall_suggestions")] List<string> OverallSuggestions,
        [property: JsonPropertyName("raw_model_output")] string? RawModelOutput = null
    );

    public record CriterionCoachingDto(
        [property: JsonPropertyName("name")] string Name,
        [property: JsonPropertyName("current_score")] int CurrentScore,
        [property: JsonPropertyName("diagnosis")] string Diagnosis,
        [property: JsonPropertyName("methods")] List<string> Methods,
        [property: JsonPropertyName("application")] string Application
    );

    public record IdeaDevelopmentDto(
        [property: JsonPropertyName("core_claim")] string CoreClaim,
        [property: JsonPropertyName("directions")] List<string> Directions,
        [property: JsonPropertyName("evidence_to_look_for")] List<string>? EvidenceToLookFor = null
    );

    public record CoachingResultDto(
        [property: JsonPropertyName("focus_criteria")] List<CriterionCoachingDto> FocusCriteria,
        [property: JsonPropertyName("idea_development")] IdeaDevelopmentDto IdeaDevelopment,
        [property: JsonPropertyName("raw_model_output")] string? RawModelOutput = null
    );

    public record ArgumentCoachingRequest(
        [property: JsonPropertyName("request")] EvaluateArgumentRequest Request,
        [property: JsonPropertyName("evaluation")] EvaluateArgumentResponse Evaluation
    );

    public record RoundCoachingRequest(
        [property: JsonPropertyName("request")] EvaluateRoundRequest Request,
        [property: JsonPropertyName("evaluation")] EvaluateRoundResponse Evaluation
    );
}
