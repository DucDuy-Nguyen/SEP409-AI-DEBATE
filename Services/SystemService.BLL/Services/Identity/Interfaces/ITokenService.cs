using System;
using System.Collections.Generic;
using SystemService.DAL.Entities.Identity;

namespace SystemService.BLL.Services.Identity.Interfaces
{
    public interface ITokenService
    {
        (string Token, DateTime ExpiresAt) GenerateToken(User user, IEnumerable<string> roles);
    }
}
