using Microsoft.Extensions.Configuration;
using Microsoft.IdentityModel.Tokens;
using System;
using System.Collections.Generic;
using System.IdentityModel.Tokens.Jwt;
using System.Security.Claims;
using System.Text;
using SystemService.Models.Entities.Identity;
using SystemService.Services.Identity.Interfaces;

namespace SystemService.Services.Identity.Implementations
{
    public class TokenService : ITokenService
    {
        private readonly IConfiguration _configuration;

        public TokenService(IConfiguration configuration)
        {
            _configuration = configuration;
        }

        public (string Token, DateTime ExpiresAt) GenerateToken(User user, IEnumerable<string> roles)
        {
            var key = _configuration["Jwt:Key"] ?? throw new InvalidOperationException("Jwt:Key configuration is missing.");
            var issuer = _configuration["Jwt:Issuer"] ?? "AIDebatePlatform";
            var audience = _configuration["Jwt:Audience"] ?? "AIDebatePlatform";
            var expireMinutesStr = _configuration["Jwt:ExpireMinutes"] ?? "60";
            if (!double.TryParse(expireMinutesStr, out double expireMinutes))
            {
                expireMinutes = 60;
            }

            var claims = new List<Claim>
            {
                new Claim(ClaimTypes.NameIdentifier, user.UserId.ToString()),
                new Claim(ClaimTypes.Email, user.Email),
                new Claim(ClaimTypes.Name, user.FullName)
            };

            foreach (var role in roles)
            {
                claims.Add(new Claim(ClaimTypes.Role, role));
            }

            var securityKey = new SymmetricSecurityKey(Encoding.UTF8.GetBytes(key));
            var credentials = new SigningCredentials(securityKey, SecurityAlgorithms.HmacSha256);
            var expiresAt = DateTime.UtcNow.AddMinutes(expireMinutes);

            var tokenDescriptor = new SecurityTokenDescriptor
            {
                Subject = new ClaimsIdentity(claims),
                Expires = expiresAt,
                Issuer = issuer,
                Audience = audience,
                SigningCredentials = credentials
            };

            var tokenHandler = new JwtSecurityTokenHandler();
            var securityToken = tokenHandler.CreateToken(tokenDescriptor);
            var tokenString = tokenHandler.WriteToken(securityToken);

            return (tokenString, expiresAt);
        }
    }
}
