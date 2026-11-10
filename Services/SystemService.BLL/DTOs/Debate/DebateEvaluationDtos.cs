using System;
using System.Collections.Generic;
using SystemService.BLL.DTOs.AI;

namespace SystemService.BLL.DTOs.Debate
{
    public class DebateEvaluationResponse
    {
        public int JudgementId { get; set; }
        public int SessionId { get; set; }
        public string SuggestedWinnerSide { get; set; } = null!;
        public int? WinnerParticipantId { get; set; }
        public string? WinnerSpeakerName { get; set; }
        public decimal? OverallScorePro { get; set; }
        public decimal? OverallScoreCon { get; set; }
        public decimal? OverallScore { get; set; }
        public decimal? ConfidenceScore { get; set; }
        public string? Summary { get; set; }
        public string? OverallFeedback { get; set; }
        public string? AIProvider { get; set; }
        public string? AIModel { get; set; }
        public DateTime EvaluatedAt { get; set; }

        public ParticipantEvaluationDto? ProEvaluation { get; set; }
        public ParticipantEvaluationDto? ConEvaluation { get; set; }
    }

    public class ParticipantEvaluationDto
    {
        public string Side { get; set; } = null!;
        public string SpeakerName { get; set; } = null!;
        public decimal OverallScore { get; set; }
        public Dictionary<string, decimal> StageBreakdown { get; set; } = new();
        public string ProgressTrend { get; set; } = string.Empty;
        public List<string> Strengths { get; set; } = new();
        public List<string> Weaknesses { get; set; } = new();
        public List<string> Suggestions { get; set; } = new();
        public List<RoundEvaluationDetailDto> RoundEvaluations { get; set; } = new();
    }

    public class RoundEvaluationDetailDto
    {
        public int RoundNumber { get; set; }
        public string Stage { get; set; } = null!;
        public decimal RoundScore { get; set; }
        public string ConsistencyNote { get; set; } = string.Empty;
        public List<CriterionScoreDto> Criteria { get; set; } = new();
        public List<string> Strengths { get; set; } = new();
        public List<string> Weaknesses { get; set; } = new();
        public List<string> Suggestions { get; set; } = new();

        // Kiem chung so lieu (RAG). null: judgement cu chua co kiem chung; rong: round khong kiem chung (khong topic, phe AI...)
        public List<TurnEvidenceCheckResponse>? EvidenceChecks { get; set; }
        public int? EvidenceScoreBefore { get; set; }
        public int? EvidenceScoreAfter { get; set; }
        public string? EvidenceRuleApplied { get; set; }
    }

    // Ban tra ve FE cua TurnEvidenceCheckDto (camelCase, KHONG co field error — error chi nam trong RawResponseJson va log)
    public class TurnEvidenceCheckResponse
    {
        public int TurnIndex { get; set; }
        public string Excerpt { get; set; } = string.Empty;
        public EvidenceCheckResponse EvidenceCheck { get; set; } = new();
    }

    public class EvidenceCheckResponse
    {
        public string Status { get; set; } = string.Empty;
        public List<EvidenceClaimResponse> Claims { get; set; } = new();
        public Dictionary<string, int> Counts { get; set; } = new();
        public int? EvidenceScoreBefore { get; set; }
        public int? EvidenceScoreAfter { get; set; }
        public string RuleApplied { get; set; } = string.Empty;
        public string? Version { get; set; }
    }

    public class EvidenceClaimResponse
    {
        public string Claim { get; set; } = string.Empty;
        public string Label { get; set; } = string.Empty;
        public string Reason { get; set; } = string.Empty;
        public List<EvidenceCitationResponse> Citations { get; set; } = new();
    }

    public class EvidenceCitationResponse
    {
        public string FactId { get; set; } = string.Empty;
        public string Content { get; set; } = string.Empty;
        public string? Citation { get; set; }
        public string? Stance { get; set; }
    }

    public class SingleArgumentEvaluationResponse
    {
        public int ArgumentId { get; set; }
        public int SessionId { get; set; }
        public int RoundNumber { get; set; }
        public string Stage { get; set; } = null!;
        public string Side { get; set; } = null!;
        public string SpeakerName { get; set; } = null!;
        public decimal OverallScore { get; set; }
        public string OverallReasoning { get; set; } = null!;
        public List<CriterionScoreDto> Criteria { get; set; } = new();
        public List<string> Strengths { get; set; } = new();
        public List<string> Weaknesses { get; set; } = new();
        public List<string> Suggestions { get; set; } = new();
    }
}
