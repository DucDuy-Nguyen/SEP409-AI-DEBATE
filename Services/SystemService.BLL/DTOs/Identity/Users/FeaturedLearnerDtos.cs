using System;
using System.ComponentModel.DataAnnotations;

namespace SystemService.BLL.DTOs.Identity.Users
{
    /// <summary>GET api/learners/featured query: the window, how many learners, and the debates a learner needs.</summary>
    public class FeaturedLearnersQuery
    {
        // Debates that ended in the last N days (0 = all time)
        [Range(0, 365)]
        public int Days { get; set; } = 30;

        [Range(1, 20)]
        public int Limit { get; set; } = 5;

        // Scored debates a learner needs to be listed: one lucky debate should not top the list
        [Range(1, 50)]
        public int MinDebates { get; set; } = 2;
    }

    /// <summary>A learner (Member, not Admin / Lecturer) ranked by the AI scores of their completed debates.</summary>
    public class FeaturedLearnerDto
    {
        public int Rank { get; set; }
        public int UserId { get; set; }
        public string FullName { get; set; } = null!;
        public string? AvatarUrl { get; set; }
        // Completed debates with an AI score for this learner's side, in the window
        public int DebatesCompleted { get; set; }
        // Debates where this learner's side scored higher than the other side
        public int Wins { get; set; }
        public decimal WinRate { get; set; }
        // AI score of the learner's side, 0-10, averaged / best over those debates
        public decimal AverageScore { get; set; }
        public decimal BestScore { get; set; }
        public DateTime LastDebateAt { get; set; }
    }
}
