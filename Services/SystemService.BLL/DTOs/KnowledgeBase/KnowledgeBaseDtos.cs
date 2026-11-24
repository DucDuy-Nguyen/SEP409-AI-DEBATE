using System;
using System.Collections.Generic;
using System.ComponentModel.DataAnnotations;

namespace SystemService.BLL.DTOs.KnowledgeBase
{
    public class CreateKnowledgeSourceRequest
    {
        [Required]
        public string Topic { get; set; } = string.Empty;

        public string SourceType { get; set; } = "manual";

        [MaxLength(300)]
        public string? Title { get; set; }

        [MaxLength(1000)]
        public string? Url { get; set; }

        [MaxLength(500)]
        public string? Citation { get; set; }

        public DateOnly? PublishedDate { get; set; }

        public string? RawText { get; set; }

        public List<string> Facts { get; set; } = new();

        public bool AutoApprove { get; set; } = false;

        [Range(1, 10)]
        public int ChunkSentences { get; set; } = 3;

        [Range(0, 5)]
        public int ChunkOverlap { get; set; } = 1;
    }

    public class UpdateFactRequest
    {
        public string? Content { get; set; }

        [MaxLength(500)]
        public string? Citation { get; set; }

        public DateOnly? PublishedDate { get; set; }
    }

    public class UpdateFactStatusRequest
    {
        [Required]
        public string Status { get; set; } = string.Empty;
    }

    public class BatchUpdateFactStatusRequest
    {
        [Required]
        [MinLength(1)]
        public List<Guid> FactIds { get; set; } = new();

        [Required]
        public string Status { get; set; } = string.Empty;
    }
}

