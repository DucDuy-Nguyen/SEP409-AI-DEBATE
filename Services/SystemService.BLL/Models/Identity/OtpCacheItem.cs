using System;

namespace SystemService.BLL.Models.Identity
{
    public class OtpCacheItem
    {
        public string Email { get; set; } = null!;
        public string Code { get; set; } = null!;
        public string Type { get; set; } = null!;
        public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
    }
}
