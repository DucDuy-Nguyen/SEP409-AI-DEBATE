using System.Collections.Generic;
using IdentityService.Models;

namespace IdentityService.Services.Interfaces
{
    public interface IJwtService
    {
        string GenerateAccessToken(User user, List<string> roles);
        string GenerateRefreshToken();
        int GetAccessTokenExpirationMinutes();
        int GetRefreshTokenExpirationDays();
    }
}
