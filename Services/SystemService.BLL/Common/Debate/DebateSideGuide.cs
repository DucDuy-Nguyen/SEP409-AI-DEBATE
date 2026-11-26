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
        private static readonly string[] MetaDescriptionPrefixes =
        {
            "discuss ",
            "debate whether ",
            "analyze ",
            "explore ",
            "examine "
        };

        /// <summary>
        /// Resolves the canonical debate Motion (resolution) from a Topic entity so the UI, PRO/CON guides,
        /// AI Opponent, AI Hint, and AI Evaluator all debate the exact same proposition.
        /// </summary>
        public static string ResolveMotion(Topic? topic)
        {
            if (topic == null) return "Debate motion";
            var title = topic.Title?.Trim();
            var description = topic.Description?.Trim();

            if (string.IsNullOrWhiteSpace(description))
            {
                return string.IsNullOrWhiteSpace(title) ? "Debate motion" : title;
            }
            if (string.IsNullOrWhiteSpace(title))
            {
                return description;
            }

            // Standard seeded topics store the debatable Motion in Title (e.g. "Social media does more harm than good")
            // and a meta-prompt/context in Description (e.g. "Discuss the positive and negative social impacts of social media.").
            foreach (var prefix in MetaDescriptionPrefixes)
            {
                if (description.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
                {
                    return title;
                }
            }

            // Otherwise, Description holds the full motion proposition (e.g. "AI cần luật quốc tế" when Title is "Luật AI").
            return description;
        }

        public static string For(Topic? topic, DebateSide side)
        {
            // Note: Topic.ProGuide / ConGuide live on main; on payment we use the generic guide built from ResolveMotion.
            return Generic(ResolveMotion(topic), side);
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
