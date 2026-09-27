using System;

namespace SystemService.BLL.DTOs.Competition.Team
{
    public class CompetitionTeamMemberResponse
    {
        public long TeamMemberId { get; set; }
        public int UserId { get; set; }
        public string FullName { get; set; } = string.Empty;
        public string Email { get; set; } = string.Empty;
        public string? AvatarUrl { get; set; }
        public DateTime JoinedAt { get; set; }
    }
}
