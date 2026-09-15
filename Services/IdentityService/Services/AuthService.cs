using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using IdentityService.DTOs.Auth;
using IdentityService.DTOs.Users;
using IdentityService.Models;
using IdentityService.Repositories.Interfaces;
using IdentityService.Services.Interfaces;

namespace IdentityService.Services
{
    public class AuthService : IAuthService
    {
        private readonly IUserRepository _userRepository;
        private readonly IJwtService _jwtService;

        public AuthService(IUserRepository userRepository, IJwtService jwtService)
        {
            _userRepository = userRepository;
            _jwtService = jwtService;
        }

        public async Task<AuthResponse> RegisterAsync(RegisterRequest request)
        {
            if (await _userRepository.ExistsByEmailAsync(request.Email))
            {
                throw new InvalidOperationException("Email address is already in use.");
            }

            var user = new User
            {
                FullName = request.FullName,
                Email = request.Email,
                PasswordHash = BCrypt.Net.BCrypt.HashPassword(request.Password),
                DateOfBirth = request.DateOfBirth,
                Gender = request.Gender,
                PhoneNumber = request.PhoneNumber,
                IsEmailVerified = false,
                IsActive = true,
                CreatedAt = DateTime.UtcNow
            };

            await _userRepository.AddUserAsync(user);
            await _userRepository.SaveChangesAsync();

            // Assign default Member role
            var memberRole = await _userRepository.GetRoleByNameAsync("Member");
            if (memberRole != null)
            {
                var userRole = new UserRole
                {
                    UserId = user.UserId,
                    RoleId = memberRole.RoleId,
                    AssignedAt = DateTime.UtcNow
                };
                await _userRepository.AddUserRoleAsync(userRole);
                await _userRepository.SaveChangesAsync();
            }

            // Reload user with roles
            var registeredUser = await _userRepository.GetByIdAsync(user.UserId) ?? user;
            var roles = registeredUser.UserRoles.Select(ur => ur.Role.RoleName).ToList();

            return await GenerateAuthResponseAsync(registeredUser, roles);
        }

        public async Task<AuthResponse> LoginAsync(LoginRequest request)
        {
            var user = await _userRepository.GetByEmailAsync(request.Email);
            if (user == null || !BCrypt.Net.BCrypt.Verify(request.Password, user.PasswordHash))
            {
                throw new InvalidOperationException("Invalid email or password.");
            }

            if (!user.IsActive)
            {
                throw new InvalidOperationException("User account is deactivated.");
            }

            var roles = user.UserRoles.Select(ur => ur.Role.RoleName).ToList();
            return await GenerateAuthResponseAsync(user, roles);
        }

        public async Task<AuthResponse> RefreshTokenAsync(RefreshTokenRequest request)
        {
            var refreshTokenEntity = await _userRepository.GetRefreshTokenAsync(request.RefreshToken);
            if (refreshTokenEntity == null)
            {
                throw new InvalidOperationException("Invalid refresh token.");
            }

            if (refreshTokenEntity.RevokedAt != null)
            {
                throw new InvalidOperationException("Refresh token has already been revoked.");
            }

            if (refreshTokenEntity.ExpiresAt <= DateTime.UtcNow)
            {
                throw new InvalidOperationException("Refresh token has expired.");
            }

            var user = refreshTokenEntity.User;
            if (user == null || !user.IsActive)
            {
                throw new InvalidOperationException("User account is inactive or not found.");
            }

            // Refresh Token Rotation
            string newRefreshTokenString = _jwtService.GenerateRefreshToken();
            refreshTokenEntity.RevokedAt = DateTime.UtcNow;
            refreshTokenEntity.ReplacedByToken = newRefreshTokenString;
            await _userRepository.UpdateRefreshTokenAsync(refreshTokenEntity);

            var roles = user.UserRoles.Select(ur => ur.Role.RoleName).ToList();

            var newRefreshToken = new RefreshToken
            {
                UserId = user.UserId,
                Token = newRefreshTokenString,
                CreatedAt = DateTime.UtcNow,
                ExpiresAt = DateTime.UtcNow.AddDays(_jwtService.GetRefreshTokenExpirationDays())
            };
            await _userRepository.SaveRefreshTokenAsync(newRefreshToken);
            await _userRepository.SaveChangesAsync();

            string accessToken = _jwtService.GenerateAccessToken(user, roles);

            return new AuthResponse
            {
                AccessToken = accessToken,
                RefreshToken = newRefreshTokenString,
                ExpiresAt = DateTime.UtcNow.AddMinutes(_jwtService.GetAccessTokenExpirationMinutes()),
                User = MapToUserResponse(user, roles)
            };
        }

        public async Task LogoutAsync(LogoutRequest request)
        {
            var refreshTokenEntity = await _userRepository.GetRefreshTokenAsync(request.RefreshToken);
            if (refreshTokenEntity != null && refreshTokenEntity.RevokedAt == null)
            {
                refreshTokenEntity.RevokedAt = DateTime.UtcNow;
                await _userRepository.UpdateRefreshTokenAsync(refreshTokenEntity);
                await _userRepository.SaveChangesAsync();
            }
        }

        private async Task<AuthResponse> GenerateAuthResponseAsync(User user, List<string> roles)
        {
            string accessToken = _jwtService.GenerateAccessToken(user, roles);
            string refreshTokenString = _jwtService.GenerateRefreshToken();

            var refreshToken = new RefreshToken
            {
                UserId = user.UserId,
                Token = refreshTokenString,
                CreatedAt = DateTime.UtcNow,
                ExpiresAt = DateTime.UtcNow.AddDays(_jwtService.GetRefreshTokenExpirationDays())
            };

            await _userRepository.SaveRefreshTokenAsync(refreshToken);
            await _userRepository.SaveChangesAsync();

            return new AuthResponse
            {
                AccessToken = accessToken,
                RefreshToken = refreshTokenString,
                ExpiresAt = DateTime.UtcNow.AddMinutes(_jwtService.GetAccessTokenExpirationMinutes()),
                User = MapToUserResponse(user, roles)
            };
        }

        private static UserResponse MapToUserResponse(User user, List<string> roles)
        {
            return new UserResponse
            {
                UserId = user.UserId,
                FullName = user.FullName,
                Email = user.Email,
                AvatarUrl = user.AvatarUrl,
                DateOfBirth = user.DateOfBirth,
                Gender = user.Gender,
                PhoneNumber = user.PhoneNumber,
                IsActive = user.IsActive,
                Roles = roles
            };
        }
    }
}
