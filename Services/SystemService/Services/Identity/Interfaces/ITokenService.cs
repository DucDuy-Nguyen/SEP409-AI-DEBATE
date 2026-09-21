using System;
using System.Collections.Generic;
using SystemService.Models.Entities.Identity;

namespace SystemService.Services.Identity.Interfaces
{
    public interface ITokenService
    {
        (string Token, DateTime ExpiresAt) GenerateToken(User user, IEnumerable<string> roles);
    }
}
