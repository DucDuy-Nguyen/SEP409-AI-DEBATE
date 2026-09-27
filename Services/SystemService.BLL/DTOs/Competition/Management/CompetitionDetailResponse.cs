using System;

namespace SystemService.BLL.DTOs.Competition.Management
{
    public class CompetitionDetailResponse : CompetitionResponse
    {
        public string CreatedByName { get; set; } = string.Empty;
        public string? FormatName { get; set; }
    }
}
