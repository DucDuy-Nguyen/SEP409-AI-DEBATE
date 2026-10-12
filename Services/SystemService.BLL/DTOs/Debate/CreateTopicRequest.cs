using System.ComponentModel.DataAnnotations;

namespace SystemService.BLL.DTOs.Debate
{
    public class CreateTopicRequest
    {
        [Required(ErrorMessage = "Title is required.")]
        [MaxLength(300, ErrorMessage = "Title cannot exceed 300 characters.")]
        public string Title { get; set; } = null!;

        public string? Description { get; set; }

        [MaxLength(100, ErrorMessage = "Category cannot exceed 100 characters.")]
        public string? Category { get; set; }

        [MaxLength(20)]
        public string Difficulty { get; set; } = "Medium";
    }
}
