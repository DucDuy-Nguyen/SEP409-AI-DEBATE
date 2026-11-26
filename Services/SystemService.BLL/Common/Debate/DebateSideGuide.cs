using SystemService.DAL.Entities.Debate;
using SystemService.DAL.Entities.Debate.Enums;

namespace SystemService.BLL.Common.Debate
{
    public static class DebateSideGuideLimits
    {
        public const int MaxLength = 1000;
    }

    /// <summary>
    /// What each side has to do in a debate, shown to the debaters: the topic's own ProGuide / ConGuide when it has
    /// one, else a generic text built from its title, so every topic (old ones too) tells PRO and CON their task.
    /// </summary>
    public static class DebateSideGuide
    {
        public static string For(Topic? topic, DebateSide side)
        {
            var custom = Clean(side == DebateSide.PRO ? topic?.ProGuide : topic?.ConGuide);
            return custom ?? Generic(topic?.Title, side);
        }

        public static string Generic(string? title, DebateSide side)
        {
            var motion = string.IsNullOrWhiteSpace(title) ? "kiến nghị của trận đấu" : $"kiến nghị \"{title.Trim()}\"";
            return side == DebateSide.PRO
                ? $"Phe ỦNG HỘ: bạn bảo vệ {motion}. Hãy chứng minh kiến nghị đúng và nên được thực hiện bằng lý lẽ, " +
                  "ví dụ và số liệu cụ thể; chỉ ra lợi ích nó mang lại; phản bác các luận điểm của phe Phản đối và " +
                  "kết luận vì sao lợi ích lớn hơn rủi ro."
                : $"Phe PHẢN ĐỐI: bạn bác bỏ {motion}. Hãy chỉ ra điểm yếu, rủi ro, chi phí hoặc hệ quả xấu của kiến " +
                  "nghị bằng lý lẽ, ví dụ và số liệu cụ thể; phản bác trực tiếp các luận điểm của phe Ủng hộ và kết luận " +
                  "vì sao không nên chấp nhận kiến nghị.";
        }

        /// <summary>Trimmed text, or null for empty / whitespace (= use the generic text).</summary>
        public static string? Clean(string? guide)
        {
            return string.IsNullOrWhiteSpace(guide) ? null : guide.Trim();
        }
    }
}
