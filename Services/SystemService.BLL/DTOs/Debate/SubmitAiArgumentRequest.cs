namespace SystemService.BLL.DTOs.Debate
{
    public class SubmitAiArgumentRequest
    {
        // Validated in DebateService (not via DataAnnotations) so errors use the ApiResponse wrapper.
        public string? Content { get; set; }

        // 0-based index into DebateTurnOrder (0..5). Nullable so a missing value is rejected instead of defaulting to 0.
        public int? TurnIndex { get; set; }
    }
}
