using System;
using System.Collections.Generic;
using System.Linq;

namespace SystemService.BLL.Common.Debate
{
    /// <summary>
    /// The fixed set of topic categories. Topic.Category stores the code (e.g. "technology"); the web shows the
    /// Vietnamese label. There is no catch-all "General" category: every topic belongs to one of these.
    /// Each has a fact base in the AI Evaluator, so their sessions get the evidence check.
    /// </summary>
    public static class TopicCategories
    {
        public sealed record Category(string Code, string Label, bool HasEvidence);

        public static readonly IReadOnlyList<Category> All = new[]
        {
            new Category("education", "Giáo dục", true),
            new Category("technology", "Công nghệ", true),
            new Category("society", "Xã hội", true),
        };

        public const string InvalidMessage =
            "Danh mục không hợp lệ. Chọn một trong: Giáo dục, Công nghệ, Xã hội.";

        /// <summary>
        /// The code of a category given as its code or its Vietnamese label (case and spaces ignored), or null when it
        /// is none of them ("General", "Chung", a typo, empty).
        /// </summary>
        public static string? Normalize(string? value)
        {
            var v = value?.Trim();
            if (string.IsNullOrEmpty(v)) return null;
            return All.FirstOrDefault(c =>
                c.Code.Equals(v, StringComparison.OrdinalIgnoreCase) ||
                c.Label.Equals(v, StringComparison.OrdinalIgnoreCase))?.Code;
        }

        /// <summary>The fact-base topic of the AI Evaluator for a category, or null when it has none.</summary>
        public static string? EvidenceTopic(string? category)
        {
            var code = Normalize(category);
            return code != null && All.First(c => c.Code == code).HasEvidence ? code : null;
        }
    }
}
