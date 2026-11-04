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
