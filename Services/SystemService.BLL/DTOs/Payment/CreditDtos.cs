using System.Collections.Generic;
using SystemService.BLL.DTOs.AI;
using SystemService.BLL.DTOs.Debate;

namespace SystemService.BLL.DTOs.Payment
{
    public class CreditPricesResponse
    {
        public long AiPracticeRag { get; set; }
        public long AiPracticeNoRag { get; set; }
        public bool IsAiPracticeNoRagSupported { get; set; }
        public long AiHint { get; set; }
        public long CompetitionSmall { get; set; }
        public long CompetitionMedium { get; set; }
        public long CompetitionLarge { get; set; }
        public long P2p1v1 { get; set; }
        public long P2p2v2 { get; set; }
        public long CompetitionJoin { get; set; }
        public long AiEvaluatorP2p { get; set; }
        public List<CreditPriceRuleItemDto> Rules { get; set; } = new();
    }

    public class CreditPriceRuleItemDto
    {
        public string RuleCode { get; set; } = null!;
        public long CreditAmount { get; set; }
        public string? Description { get; set; }
        public bool IsActive { get; set; }
        public string Category { get; set; } = null!;
    }

    public class CompetitionPriceQuoteResponse
    {
        public string CompetitionType { get; set; } = null!;
        public string Scale { get; set; } = null!;
        public string RuleCode { get; set; } = null!;
        public int MaxParticipants { get; set; }
        public int? MaxTeams { get; set; }
        public long RequiredCredits { get; set; }
    }

    public class AiHintRequest
    {
        public int SessionId { get; set; }
        public int? ArgumentId { get; set; }
        public int? RoundNumber { get; set; }
        public string? DraftText { get; set; }
        public string? RequestId { get; set; }
    }

    public class AiHintResponse
    {
        public int SessionId { get; set; }
        public int? ArgumentId { get; set; }
        public string RequestId { get; set; } = null!;
        public long CreditsCharged { get; set; }
        public long RemainingBalance { get; set; }
        public bool AlreadyProcessed { get; set; }
        public CoachingResultDto Hint { get; set; } = null!;
        public SingleArgumentEvaluationResponse? Evaluation { get; set; }
    }
}
