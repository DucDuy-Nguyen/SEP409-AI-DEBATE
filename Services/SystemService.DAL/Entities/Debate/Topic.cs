using System;
using System.Collections.Generic;
using SystemService.DAL.Entities.Identity;

namespace SystemService.DAL.Entities.Debate
{
    public class Topic
    {
        public int TopicId { get; set; }
        public string Title { get; set; } = null!;
        public string? Description { get; set; }
        public string? Category { get; set; }
        public string Difficulty { get; set; } = "Medium";
        public int? CreatedBy { get; set; }
        public bool IsActive { get; set; } = true;
        public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
        public DateTime? UpdatedAt { get; set; }

        public User? CreatedByUser { get; set; }
        public ICollection<DebateSession> DebateSessions { get; set; } = new List<DebateSession>();
    }
}
