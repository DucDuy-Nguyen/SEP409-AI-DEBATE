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
        [property: JsonPropertyName("turns")] List<RoundTurnDto> Turns,
        // Chu de kho fact (education|environment|technology|society); null -> evaluator khong kiem chung so lieu
        [property: JsonPropertyName("topic")] string? Topic = null,
        // false: khong kiem chung round nay (phe AI trong AI practice)
        [property: JsonPropertyName("check_evidence")] bool CheckEvidence = true
    );

    // Ket qua kiem chung so lieu (RAG) — map 1-1 voi app/schemas.py cua ai-evaluator-service.
    // Field nullable bo qua khi ghi null: round response duoc gui lai /evaluate/session, ma cac field `str` / `list`
    // ben Python khong nhan null (bo qua thi Python dung gia tri mac dinh).
    public record EvidenceCitationDto(
        [property: JsonPropertyName("fact_id")] string FactId,
        [property: JsonPropertyName("content")] string Content,
        [property: JsonPropertyName("citation"), JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] string? Citation = null,
        [property: JsonPropertyName("stance"), JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] string? Stance = null
    );

    public record EvidenceClaimDto(
        [property: JsonPropertyName("claim")] string Claim,
        [property: JsonPropertyName("label")] string Label,
        [property: JsonPropertyName("reason")] string Reason,
        [property: JsonPropertyName("citations"), JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] List<EvidenceCitationDto>? Citations = null
    );

    public record EvidenceCheckSummaryDto(
        // checked | no_claims | unavailable | no_fact_base
        [property: JsonPropertyName("status")] string Status,
        [property: JsonPropertyName("claims"), JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] List<EvidenceClaimDto>? Claims = null,
        [property: JsonPropertyName("counts"), JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] Dictionary<string, int>? Counts = null,
        [property: JsonPropertyName("evidence_score_before"), JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] int? EvidenceScoreBefore = null,
        [property: JsonPropertyName("evidence_score_after"), JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] int? EvidenceScoreAfter = null,
        [property: JsonPropertyName("rule_applied"), JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] string? RuleApplied = null,
        // Ly do khi status = unavailable: chi luu RawResponseJson + log, KHONG tra ve FE
        [property: JsonPropertyName("error"), JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] string? Error = null,
        [property: JsonPropertyName("version"), JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] string? Version = null
    );

    public record TurnEvidenceCheckDto(
        [property: JsonPropertyName("turn_index")] int TurnIndex,
        [property: JsonPropertyName("excerpt")] string Excerpt,
        [property: JsonPropertyName("evidence_check")] EvidenceCheckSummaryDto EvidenceCheck
    );

    public record EvaluateRoundResponse(
        [property: JsonPropertyName("stage")] string Stage,
        [property: JsonPropertyName("round_score")] decimal RoundScore,
        [property: JsonPropertyName("criteria")] List<CriterionScoreDto> Criteria,
        [property: JsonPropertyName("consistency_note")] string ConsistencyNote,
        [property: JsonPropertyName("strengths")] List<string> Strengths,
        [property: JsonPropertyName("weaknesses")] List<string> Weaknesses,
        [property: JsonPropertyName("suggestions")] List<string> Suggestions,
        // Judgement cu / evaluator ban cu khong co cac field duoi -> null
        [property: JsonPropertyName("evidence_checks"), JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] List<TurnEvidenceCheckDto>? EvidenceChecks = null,
        [property: JsonPropertyName("evidence_score_before"), JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] int? EvidenceScoreBefore = null,
        [property: JsonPropertyName("evidence_score_after"), JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] int? EvidenceScoreAfter = null,
        [property: JsonPropertyName("evidence_rule_applied"), JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)] string? EvidenceRuleApplied = null
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
