namespace SystemService.BLL.DTOs.Debate
{
    public class SubmitAiArgumentResponse
    {
        public int TurnIndex { get; set; }

        // True when the AI argument for this turn already existed (retry); the stored argument is returned unchanged.
        public bool AlreadyRecorded { get; set; }

        public ArgumentDetailDto Argument { get; set; } = null!;
        public DebateSessionResponse Session { get; set; } = null!;
    }
}
