using System.Collections.Generic;
using System.Text.Json.Serialization;

namespace SystemService.BLL.DTOs.AI
{
    public record CreateOpponentSessionRequest(
        [property: JsonPropertyName("external_session_id")] string ExternalSessionId,
        [property: JsonPropertyName("motion")] string Motion,
        [property: JsonPropertyName("learner_side")] string LearnerSide,
        [property: JsonPropertyName("ai_side")] string AiSide,
        [property: JsonPropertyName("difficulty")] string Difficulty = "medium",
        [property: JsonPropertyName("language")] string Language = "vi"
    );

    public record CreateOpponentSessionResponse(
        [property: JsonPropertyName("opponent_session_id")] string OpponentSessionId,
        [property: JsonPropertyName("status")] string Status
    );

    public record LearnerSpeechDto(
        [property: JsonPropertyName("turn_index")] int TurnIndex,
        [property: JsonPropertyName("round_type")] string RoundType,
        [property: JsonPropertyName("text")] string Text
    );

    public record GenerateTurnRequest(
        [property: JsonPropertyName("turn_index")] int TurnIndex,
        [property: JsonPropertyName("new_learner_speeches")] List<LearnerSpeechDto> NewLearnerSpeeches
    );

    public record GenerateTurnResponse(
        [property: JsonPropertyName("turn_index")] int TurnIndex,
        [property: JsonPropertyName("round_type")] string RoundType,
        [property: JsonPropertyName("mode")] string Mode,
        [property: JsonPropertyName("speech_text")] string SpeechText
    );
}
