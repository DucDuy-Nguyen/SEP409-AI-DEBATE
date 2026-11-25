namespace SystemService.BLL.Common.Debate
{
    /// <summary>
    /// Machine-readable codes returned in ApiResponse.Errors (as ApiErrorDetail) by debate turn endpoints,
    /// so controllers can pick the HTTP status without matching message text.
    /// </summary>
    public static class DebateErrorCodes
    {
        public const string InvalidRequest = "INVALID_REQUEST";
        public const string SessionNotFound = "SESSION_NOT_FOUND";
        public const string NotParticipant = "NOT_PARTICIPANT";
        public const string NotAiSession = "NOT_AI_SESSION";
        public const string NotAiTurn = "NOT_AI_TURN";
        public const string NotYourTurn = "NOT_YOUR_TURN";
        public const string TurnOutOfOrder = "TURN_OUT_OF_ORDER";
        public const string SessionNotInProgress = "SESSION_NOT_IN_PROGRESS";
        public const string SessionCompleted = "SESSION_COMPLETED";
        public const string ConcurrentSubmission = "CONCURRENT_SUBMISSION";
        public const string PreparationInProgress = "PREPARATION_IN_PROGRESS";
        // Team call (2v2): the caller has no human teammate / the preparation minute (the only time to call) is over
        public const string NoTeammate = "NO_TEAMMATE";
        public const string TeamCallClosed = "TEAM_CALL_CLOSED";
    }
}
