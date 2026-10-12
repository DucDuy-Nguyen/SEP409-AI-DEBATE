namespace SystemService.BLL.DTOs.Debate
{
    public class TopicQueryParameters
    {
        public string? SearchTerm { get; set; }
        public string? Category { get; set; }
        public string? Difficulty { get; set; }
        public bool? IsActive { get; set; } = true;
        public int PageNumber { get; set; } = 1;
        public int PageSize { get; set; } = 20;
    }
}
