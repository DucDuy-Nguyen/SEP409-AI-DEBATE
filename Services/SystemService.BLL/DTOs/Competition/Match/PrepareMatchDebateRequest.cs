using System.ComponentModel.DataAnnotations;

namespace SystemService.BLL.DTOs.Competition.Match
{
    public class PrepareMatchDebateRequest
    {
        [Required]
        public int TopicId { get; set; }
    }
}
