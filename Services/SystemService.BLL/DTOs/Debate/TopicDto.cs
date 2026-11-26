using System;

namespace SystemService.BLL.DTOs.Debate
{
    public class TopicDto
    {
        public int TopicId { get; set; }
        public string Title { get; set; } = null!;
        public string? Description { get; set; }
        public string? Category { get; set; }
        public string Difficulty { get; set; } = "Medium";
        // What PRO / CON have to do: the topic's own text, else a generic one built from the title (never null).
        // HasCustomGuides = false means the generic text: an edit form should then start empty, not with it.
        public string ProGuide { get; set; } = null!;
        public string ConGuide { get; set; } = null!;
        public bool HasCustomGuides { get; set; }
        public int? CreatedBy { get; set; }
        public string? CreatedByUserName { get; set; }
        public bool IsActive { get; set; }
        public DateTime CreatedAt { get; set; }
        public DateTime? UpdatedAt { get; set; }
    }
}
