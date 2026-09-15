using System;
using System.Collections.Generic;
using System.IdentityModel.Tokens.Jwt;
using System.Security.Claims;
using System.Security.Cryptography;
using System.Text;
using IdentityService.Models;
using IdentityService.Services.Interfaces;
using Microsoft.Extensions.Configuration;
using Microsoft.IdentityModel.Tokens;

namespace IdentityService.Services
{
    public class JwtService : IJwtService
    {
        private readonly IConfiguration _config;

        public JwtService(IConfiguration config)
        {
            _config = config;
        }

        public string GenerateAccessToken(User user, List<string> roles)
        {
            var key = _config["Jwt:Key"] ?? "CHANGE_THIS_TO_A_LONG_DEVELOPMENT_SECRET_KEY_123456";
            var issuer = _config["Jwt:Issuer"] ?? "DebatePracticePlatform";
            var audience = _config["Jwt:Audience"] ?? "DebatePracticePlatform";
            var expirationMinutes = GetAccessTokenExpirationMinutes();

            var securityKey = new SymmetricSecurityKey(Encoding.UTF8.GetBytes(key));
            var credentials = new SigningCredentials(securityKey, SecurityAlgorithms.HmacSha256);

            var claims = new List<Claim>
            {
                new Claim(JwtRegisteredClaimNames.Sub, user.UserId.ToString()),
                new Claim(ClaimTypes.NameIdentifier, user.UserId.ToString()),
                new Claim(JwtRegisteredClaimNames.Email, user.Email),
                new Claim(ClaimTypes.Email, user.Email),
                new Claim(JwtRegisteredClaimNames.Jti, Guid.NewGuid().ToString())
            };

            foreach (var role in roles)
            {
                claims.Add(new Claim(ClaimTypes.Role, role));
            }

            var token = new JwtSecurityToken(
                issuer: issuer,
                audience: audience,
                claims: claims,
                expires: DateTime.UtcNow.AddMinutes(expirationMinutes),
                signingCredentials: credentials);

            return new JwtSecurityTokenHandler().WriteToken(token);
        }

        public string GenerateRefreshToken()
        {
            var randomNumber = new byte[64];
            using var rng = RandomNumberGenerator.Create();
            rng.GetBytes(randomNumber);
            return Convert.ToBase64String(randomNumber);
        }

        public int GetAccessTokenExpirationMinutes()
        {
            return int.TryParse(_config["Jwt:AccessTokenExpirationMinutes"], out int minutes) ? minutes : 60;
        }

        public int GetRefreshTokenExpirationDays()
        {
            return int.TryParse(_config["Jwt:RefreshTokenExpirationDays"], out int days) ? days : 7;
        }
    }
}
