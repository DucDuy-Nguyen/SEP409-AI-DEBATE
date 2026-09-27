namespace SystemService.BLL.DTOs.Competition.Management
{
    public class CompetitionQueryRequest
    {
        public string? Status { get; set; }
        public string? CompetitionType { get; set; }
        public bool? IsPublic { get; set; }
        public string? Keyword { get; set; }
    }
}
