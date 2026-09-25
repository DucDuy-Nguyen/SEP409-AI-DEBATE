using System.Collections.Generic;

namespace SystemService.BLL.DTOs.Competition.Team
{
    public class CompetitionTeamDetailResponse : CompetitionTeamResponse
    {
        public string CaptainName { get; set; } = string.Empty;
        public List<CompetitionTeamMemberResponse> Members { get; set; } = new List<CompetitionTeamMemberResponse>();
    }
}
