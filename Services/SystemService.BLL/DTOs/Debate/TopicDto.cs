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
        public int? CreatedBy { get; set; }
        public string? CreatedByUserName { get; set; }
        public bool IsActive { get; set; }
        public DateTime CreatedAt { get; set; }
        public DateTime? UpdatedAt { get; set; }
    }
}
